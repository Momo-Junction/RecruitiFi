"""Synthetic fetched profile text -> actual worker function -> real local MiniLM.

Transport is mocked; production SQLite and real profiles are never read. The
caller must configure the loopback model URL and server-side bearer token.
"""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import database
from backend.evidence import jobs,profile_matching,public_profiles,storage
from experiments.github_evidence_e2e import prepare


def main():
    with tempfile.TemporaryDirectory(prefix='recruitifi-public-profile-e2e-') as d:
        path=Path(d)/'synthetic.sqlite3'
        with sqlite3.connect(path) as c:
            prepare(c,'https://github.com/SyntheticOwner');c.execute('PRAGMA query_only=OFF')
            c.execute("UPDATE profile_materials SET description='' WHERE id=7")
        with patch.object(database,'DB_PATH',path),patch.dict('os.environ',TALENTMATCH_AI_FETCH_PUBLIC_PROFILES='1',TALENTMATCH_AI_CONSENTED_MODE='1',TALENTMATCH_AI_CANDIDATES='402',TALENTMATCH_AI_JOB_MATCHING='1',TALENTMATCH_AI_DEMO_TOKEN='synthetic-e2e-only-operator-token-123456'):
            for category,url in (('github','https://github.com/SyntheticOwner'),):
                with database.connect() as c:
                    c.execute('UPDATE profile_materials SET category=?,url=? WHERE id=7',(category,url))
                    row=c.execute('SELECT * FROM profile_materials WHERE id=7').fetchone()
                    c.execute('DELETE FROM ai_material_consents')
                    c.execute('INSERT INTO ai_material_consents(material_id,candidate_id,digest) VALUES(7,402,?)',(profile_matching.digest_material(row),))
                with patch.object(public_profiles,'fetch_profile',return_value={'status':'retrieved','text':'Synthetic Python and FastAPI REST APIs. Built React interfaces with TypeScript.','references':[url],'untrusted':True}):
                    report=jobs.analyze_material({'candidate_id':402,'material_id':7,'top_k':3},time.time()+120)
                with database.connect() as c:
                    ids=storage.save_analysis(402,report,connection=c)
                    assert ids and report['ai_job_matches']['status']=='completed'
                    assert report['ai_job_matches']['sources'][0]['external_content_analyzed']
                    assert c.execute('SELECT description FROM profile_materials WHERE id=7').fetchone()[0]==''
                print(json.dumps({'category':category,'status':'PASS','real_local_model':True,'mocked_public_retrieval':True,'stored_source_kind':'public_'+category+'_profile','manual_description_required':False,'job_scores':len(report['ai_job_matches']['matches'])}))


if __name__=='__main__':main()
