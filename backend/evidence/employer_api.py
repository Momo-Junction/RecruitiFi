"""Read-only, explicitly granted synthetic findings; no private uploads."""
from fastapi import APIRouter, Request, Response, HTTPException
from ..database import connect
from .sessions import session, employer_grants
from .jobs import configuration
from .storage import list_analysis_runs, get_analysis
from .api import Identity

router = APIRouter(prefix='/api/companies/{company_id}')


@router.get('/candidates/{candidate_id}/evidence-analysis')
def findings(company_id: Identity, candidate_id: Identity, request: Request, response: Response):
    _, account = session(request)
    try:
        approved = configuration()[1]
        permitted = employer_grants(approved).get(str(company_id), [])
    except ValueError:
        raise HTTPException(403, 'Synthetic Employer access is unavailable.') from None
    if account.get('role') != 'employer' or account.get('company_id') != company_id or candidate_id not in approved or candidate_id not in permitted:
        raise HTTPException(403, 'This synthetic candidate is not shared with your Employer account.')
    response.headers['Cache-Control'] = 'no-store'
    with connect() as connection:
        if not connection.execute('SELECT 1 FROM companies WHERE id=?',(company_id,)).fetchone() or not connection.execute('SELECT 1 FROM candidates WHERE id=?',(candidate_id,)).fetchone():
            raise HTTPException(404, 'Synthetic profile not found.')
        analyses, seen = [], set()
        runs = list_analysis_runs(candidate_id,connection=connection)
        for run in runs:
            if run['material_id'] in seen:
                continue
            seen.add(run['material_id'])
            if run['status'] not in ('complete','limited'):
                continue
            result = get_analysis(candidate_id,run['id'],connection=connection)
            # No document excerpts, private filenames, download URLs or BLOBs.
            result['sources'] = [s if s['source_type'] in ('project_link','github_metadata','github_readme','github_file') else
                {'id':s['id'],'run_id':s['run_id'],'source_type':'private_document','evidence_field':'Private document (contents withheld)',
                 'excerpt':'','file_path':None,'source_reference':None,'redacted':True,'untrusted':True}
                for s in result['sources']]
            permitted_sources = {s['id'] for s in result['sources']}
            private_sources = {s['id'] for s in result['sources'] if s.get('redacted')}
            result['findings'] = [f for f in result['findings'] if f['source_id'] in permitted_sources]
            for finding in result['findings']:
                if finding['source_id'] in private_sources:
                    finding['observed_value'] = None
            if result['findings']:
                analyses.append(result)
        latest = connection.execute('SELECT status FROM evidence_analysis_jobs WHERE candidate_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(candidate_id,)).fetchone()
        state = 'pending' if latest and latest['status']=='queued' else 'running' if latest and latest['status']=='running' else 'failed' if (latest and latest['status'] in ('failed','timed_out','cancelled','interrupted')) or (not analyses and any(r['status'] in ('failed','partial') for r in runs)) else 'completed' if analyses else 'missing'
        return {'candidate_id':candidate_id,'status':state,'analyses':analyses}
