"""Disposable HTTP/worker integration with synthetic PDFs and a real loopback model.

Requires TALENTMATCH_EMBED_URL/TOKEN in the server environment. No real app DB,
GitHub retrieval, candidate documents or cluster access. Prints status only.
"""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.test_evidence import synthetic_pdf
from backend.database import SCHEMA_PATH


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-model-unavailable',action='store_true')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='recruitifi-analysis-e2e-') as directory:
        database=Path(directory)/'synthetic.sqlite3'
        with sqlite3.connect(database) as c:
            c.executescript(SCHEMA_PATH.read_text())
            c.executemany('INSERT INTO skills VALUES(?,?,?,?)',[(1,'urn:test:1','Python','IT'),(2,'urn:test:2','React','IT')])
            c.execute("INSERT INTO candidates VALUES(402,'SYNTHETIC','Fabricated test','test@example.invalid',0,0,'{}',0,'[]')")
            c.execute("INSERT INTO companies VALUES(1,'Fabricated company','IT','S1',0,'English',50,'[]','[]')")
            c.execute("INSERT INTO job_openings VALUES(501,1,'Fabricated job','it','Test only','[{\"skill_id\":1,\"weight\":70}]','[]',1)")
            c.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(1,402,'project','Synthetic Python API','Built Python REST APIs','https://example.invalid/project')")
            for i,image in ((2,False),(3,True)):
                content=synthetic_pdf(image_only=image)
                c.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,filename,content_type,content) VALUES(?,402,'cv','Synthetic CV','','fixture.pdf','application/pdf',?)",(i,content))
        with sqlite3.connect(database) as c:
            for i,category in ((4,'project'),(5,'certificate'),(6,'research')):
                c.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,filename,content_type,content) VALUES(?,402,?,'Synthetic resource','Fabricated Python API','fixture.pdf','application/pdf',?)",(i,category,synthetic_pdf()))
            for i,category in ((7,'linkedin'),(8,'website')):
                c.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(?,402,?,'Synthetic resource','Fabricated Python API','https://example.invalid/never-fetch')",(i,category))
            c.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,filename,content_type,content) VALUES(9,402,'certificate','Synthetic image','Fabricated Python API','fixture.png','image/png',?)",(b'\x89PNG\r\n\x1a\n synthetic only',))
        with sqlite3.connect(database) as c:
            c.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(10,402,'linkedin','LinkedIn','','https://www.linkedin.com/in/synthetic-only')")
            c.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(11,402,'github','GitHub','','https://github.com/SyntheticOwner')")
            c.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(12,402,'github','GitHub','Fabricated Python API','https://github.com/SyntheticOwner')")
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        password=secrets.token_urlsafe(20)
        env=os.environ.copy()
        env.update(TALENTMATCH_DB=str(database),TALENTMATCH_HOSTED_DEMO='0',TALENTMATCH_SERVE_FRONTEND='0',TALENTMATCH_PUBLIC_ORIGIN='',TALENTMATCH_AI_CONSENTED_MODE='1',TALENTMATCH_AI_CANDIDATES='402',TALENTMATCH_AI_SYNTHETIC_DEMO='0',TALENTMATCH_AI_JOB_MATCHING='1',TALENTMATCH_VERIFIED_DEMO_LOGIN='1',TALENTMATCH_AI_DEMO_TOKEN=secrets.token_urlsafe(40),TALENTMATCH_AI_SESSION_SECRET=secrets.token_urlsafe(40),TALENTMATCH_AI_DEMO_ACCOUNTS=json.dumps({'talent-001':password}),TALENTMATCH_AI_EMPLOYER_ACCESS='{}')
        base=f'http://127.0.0.1:{port}';jar=http.cookiejar.CookieJar()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
        def request(path,body=None,csrf=None,method=None):
            headers={'Origin':base,'Content-Type':'application/json'}
            if csrf:headers['X-Recruitifi-CSRF']=csrf
            req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
            try:
                with opener.open(req,timeout=10) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as e:return e.code,json.load(e)
        with open(Path(directory)/'server.log','w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:
                        if request('/healthz')[0]==200:break
                    except OSError:pass
                    time.sleep(.1)
                else:raise RuntimeError('Synthetic API startup failed')
                status,identity=request('/api/evidence-session',{'account':'talent-001','password':password})
                assert status==200
                csrf=identity['csrf'];summary=[]
                for material_id in (1,2,4,5,6,7,8,9,12,3):
                    assert request('/api/ai-matches/profiles/402/consent',{'material_ids':[material_id],'confirm':True},csrf)[0]==200
                    status,accepted=request('/api/ai-matches/profiles/402/analyze',{},csrf)
                    assert status==202,(status,accepted)
                    for _ in range(300):
                        status,result=request(accepted['result_url'])
                        if result['job']['status'] not in ('queued','running'):break
                        time.sleep(.1)
                    status,profile=request('/api/ai-matches/profiles/402')
                    summary.append({'material':material_id,'job_status':result['job']['status'],'error':result['job']['error_code'],'profile_status':profile['status'],'job_scores':len(profile['matches']),'content_status':[s['content_status'] for s in profile.get('sources',[])]})
                    if material_id !=3:
                        if args.expect_model_unavailable:
                            assert result['job']['status']=='failed' and profile['status']=='unavailable',summary
                            assert profile['detail'] and not profile['matches']
                        else:assert result['job']['status']=='completed' and profile['matches'],summary
                    else:
                        assert result['job']['status']=='failed' and result['job']['error_code']=='no_extractable_text',summary
                        assert profile['detail'] and not profile['matches']
                if not args.expect_model_unavailable:
                    assert request('/api/ai-matches/profiles/402/consent',{'material_ids':[10,11,2],'confirm':True},csrf)[0]==200
                    code,accepted=request('/api/ai-matches/profiles/402/analyze',{},csrf)
                    assert code==202
                    for _ in range(300):
                        code,result=request(accepted['result_url'])
                        if result['job']['status'] not in ('queued','running'):break
                        time.sleep(.1)
                    assert result['job']['status']=='completed'
                    data=request('/api/ai-matches/profiles/402')[1]
                    assert {s['material_id'] for s in data['sources'] if s['content_status']=='not_analyzed'}=={10,11}
                    assert data['matches']
                    assert request('/api/ai-matches/profiles/402/materials/10/description',{'description':'Fabricated Python API'},csrf,method='PATCH')[0]==200
                    summary.append({'check':'bare LinkedIn + GitHub profile + CV','completed':True,'unread_links_explicitly_marked':True,'description_edit':'PASS'})
                    def reanalyze():
                        assert request('/api/ai-matches/profiles/402/consent',{'material_ids':[1],'confirm':True},csrf)[0]==200
                        code,accepted=request('/api/ai-matches/profiles/402/analyze',{},csrf)
                        assert code==202
                        for _ in range(300):
                            code,result=request(accepted['result_url'])
                            if result['job']['status'] not in ('queued','running'):break
                            time.sleep(.1)
                        assert result['job']['status']=='completed'
                        return request('/api/ai-matches/profiles/402')[1]
                    before=reanalyze()
                    assert request('/api/candidates/402/skills',[2],csrf,method='PUT')[0]==200
                    assert request('/api/ai-matches/profiles/402')[1]['status']=='stale'
                    after=reanalyze()
                    assert {j:r['score'] for j,r in before['matches'].items()}=={j:r['score'] for j,r in after['matches'].items()}
                    summary.append({'check':'skill addition','cache_invalidated':True,'claim_did_not_inflate_score':True})
                print(json.dumps(summary))
            finally:
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=='__main__':main()
