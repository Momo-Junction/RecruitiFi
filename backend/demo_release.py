"""Explicit one-time demo reset + 50 fictional jobs. Never called at startup.

Dry-run is the default; applying requires an explicit database and new backup path.
No uploads, accounts, Employer swipes, tasks or analysis history are deleted.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3

from . import database
from .models import CompanyRoleUpdate
from .notifications import reconcile_pair
from .seed_jobs import JOBS

VERSION = 'public-demo-fresh-talents-50-jobs-v1'
# Ten additional fictional positions per existing company; reuse real catalog names
# and existing requirement validation, not fabricated skill IDs or new scoring rules.
TITLES = [
    [(0,'Python API Developer'),(0,'Research Software Developer'),(0,'Scientific Backend Engineer'),(0,'Quantum Tooling Developer'),(1,'Signal Processing Engineer'),(1,'Prototype Electronics Engineer'),(1,'Embedded Lab Engineer'),(2,'Research Reporting Analyst'),(2,'Scientific Data Analyst'),(2,'Research Insights Analyst')],
    [(3,'Grid Simulation Engineer'),(3,'Energy Planning Engineer'),(3,'Renewable Systems Analyst'),(3,'Power Modeling Engineer'),(3,'Energy Research Engineer'),(4,'Equipment Logistics Planner'),(4,'Event Inventory Coordinator'),(4,'Supply Operations Coordinator'),(4,'Demo Delivery Planner'),(4,'Logistics Project Assistant')],
    [(5,'Clinical Reporting Analyst'),(5,'Health Data Coordinator'),(5,'Medical Data Quality Assistant'),(5,'Clinical Documentation Coordinator'),(5,'Synthetic Health Research Analyst'),(6,'Facilities Cleaning Assistant'),(6,'Cleaning Safety Coordinator'),(6,'Demo Laboratory Cleaning Assistant'),(6,'Facility Services Assistant'),(6,'Event Cleaning Coordinator')],
    [(7,'Cloud Operations Engineer'),(7,'Container Platform Developer'),(7,'Infrastructure Automation Engineer'),(7,'Deployment Platform Engineer'),(7,'Cloud Reliability Engineer'),(8,'Service Operations Coordinator'),(8,'Agile Delivery Assistant'),(8,'Client Project Coordinator'),(8,'Technical Delivery Coordinator'),(8,'Service Planning Analyst')],
    [(9,'Accessibility Design Assistant'),(9,'Digital Product Designer'),(9,'User Experience Research Assistant'),(9,'Interface Prototyping Designer'),(10,'Event Food Service Assistant'),(10,'Demo Catering Coordinator'),(10,'Pop-up Catering Assistant'),(11,'Client Workshop Coordinator'),(11,'Customer Discovery Assistant'),(11,'Client Research Coordinator')],
]


def plan(connection):
    names={row['name']:row['id'] for row in connection.execute('SELECT id,name FROM skills')}
    companies={row[0] for row in connection.execute('SELECT id FROM companies')}
    rows=[]
    for index,(template,title) in enumerate(item for group in TITLES for item in group):
        _,company,_,industry,description,required,preferred=JOBS[template]
        if company not in companies:raise ValueError(f'Required demo company {company} is missing; no reseeding is allowed.')
        missing=(required.keys()|preferred.keys())-names.keys()
        if missing:raise ValueError('Missing catalog skills; run the existing additive jobs initializer first.')
        groups=[[{'skill_id':names[name],'weight':weight} for name,weight in group.items()] for group in (required,preferred)]
        CompanyRoleUpdate(working_language='English',relocation_support=False,min_match_threshold=75,must_have_skills=groups[0],nice_to_have_skills=groups[1])
        rows.append((910001+index,company,title,industry,'Fictional hackathon opening, not a real vacancy. '+description,json.dumps(groups[0]),json.dumps(groups[1]),1))
    assert len(rows)==50
    return rows


def preview(connection):
    done=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_release_runs'").fetchone()
    if done and connection.execute('SELECT 1 FROM demo_release_runs WHERE version=?',(VERSION,)).fetchone():
        return {'version':VERSION,'already_applied':True,'new_jobs':0}
    rows=plan(connection)
    if connection.execute('SELECT 1 FROM job_openings WHERE id BETWEEN 910001 AND 910050').fetchone():
        raise ValueError('Reserved new job IDs are occupied; refusing to overwrite existing jobs.')
    active=connection.execute('SELECT count(*) FROM job_openings WHERE active=1').fetchone()[0]
    if active+50>128:raise ValueError('Adding 50 jobs would exceed the existing 128-active-job analysis budget.')
    if connection.execute("SELECT 1 FROM evidence_analysis_jobs WHERE status IN ('queued','running')").fetchone():
        raise ValueError('An analysis is active; wait before preparing the demo.')
    return {'version':VERSION,'already_applied':False,'new_jobs':len(rows),'active_jobs_after':active+50,
            'profiles_with_skills':connection.execute("SELECT count(*) FROM candidates WHERE json_array_length(skills)>0").fetchone()[0],
            'material_skill_links':connection.execute('SELECT count(*) FROM profile_materials WHERE skill_id IS NOT NULL').fetchone()[0],
            'talent_swipes':connection.execute("SELECT count(*) FROM swipe_decisions WHERE actor='talent'").fetchone()[0]}


def apply(connection, *, backup_path):
    """Atomic, repeatable preparation; backup before writes while blocking writers."""
    connection.execute('BEGIN IMMEDIATE')
    try:
        summary=preview(connection)
        if summary['already_applied']:
            connection.rollback();return summary
        target=Path(backup_path).absolute()
        source=database.DB_PATH.resolve()
        if target.is_symlink() or target.resolve()==source:raise ValueError('Backup must be a different, new regular file.')
        # Exclusive creation prevents overwriting either a backup or a symlink.
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        reader=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
        destination=sqlite3.connect(target)
        try:reader.backup(destination)
        finally:reader.close();destination.close()
        pairs=list(connection.execute("SELECT candidate_id,company_id FROM swipe_decisions WHERE actor='talent'"))
        connection.execute("UPDATE candidates SET skills='[]'")
        connection.execute('UPDATE profile_materials SET skill_id=NULL WHERE skill_id IS NOT NULL')
        connection.execute("DELETE FROM swipe_decisions WHERE actor='talent'")
        for candidate,company in pairs:reconcile_pair(connection,candidate,company)
        connection.executemany('INSERT INTO job_openings VALUES(?,?,?,?,?,?,?,?)',plan(connection))
        connection.execute("CREATE TABLE IF NOT EXISTS demo_release_runs(version TEXT PRIMARY KEY, completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), summary TEXT NOT NULL)")
        connection.execute('INSERT INTO demo_release_runs(version,summary) VALUES(?,?)',(VERSION,json.dumps(summary)))
        connection.commit()
        return {**summary,'applied':True}
    except BaseException:
        connection.rollback();raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    if not args.database.is_absolute() or not args.database.is_file():parser.error('--database must identify an existing absolute SQLite path.')
    if args.apply and (args.backup is None or not args.backup.is_absolute()):parser.error('--apply requires a new absolute --backup path.')
    database.DB_PATH=args.database
    if args.apply:
        with database.connect() as connection:result=apply(connection,backup_path=args.backup)
    else:
        connection=sqlite3.connect(args.database.as_uri()+'?mode=ro',uri=True);connection.row_factory=sqlite3.Row
        try:result=preview(connection)
        finally:connection.close()
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
