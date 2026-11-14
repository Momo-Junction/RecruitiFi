"""Public fictional-only demo: disposable data, mocked model, no live networking."""
import asyncio
import base64
import json
import threading
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

from . import database, test_synthetic_ai_demo as fixtures
from .demo_auth import DemoAuthMiddleware
from .evidence import public_demo_api, synthetic_demo, demo_boundary, semantic_matching, jobs


class PublicAIDemoTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.SyntheticAIDemoTests.asyncTearDown

    async def request(self,method,path,body=None,headers=()):
        target=self.app; parsed=urlsplit(path)
        async def scoped(scope,receive,send):
            await target({**scope,'query_string':parsed.query.encode()},receive,send)
        self.app=scoped
        try:
            return await fixtures.SyntheticAIDemoTests.request(self,method,parsed.path,body,headers)
        finally:self.app=target

    def setUp(self):
        fixtures.SyntheticAIDemoTests.setUp(self)
        environment = patch.dict('os.environ', TALENTMATCH_AI_PUBLIC_DEMO='1')
        environment.start(); self.addCleanup(environment.stop)
        self.app.include_router(public_demo_api.router)
        with database.connect() as connection:
            self.material = synthetic_demo.provision(connection)
        self.base = '/api/ai-demo/candidates/900001'
        self.start = self.base+f'/materials/{self.material}/analysis'

    async def completed(self, headers=()):
        status, accepted, _ = await self.request('POST', self.start, headers=headers)
        self.assertEqual(status, 202)
        for _ in range(150):
            status, result, _ = await self.request('GET', accepted['result_url'], headers=headers)
            if status == 200:
                self.assertEqual(result['job']['status'], 'completed')
                return accepted, result
            self.assertEqual(status, 202)
            await asyncio.sleep(.01)
        self.fail('Demo job did not finish.')

    async def test_direct_analysis_results_employer_and_cached_retry(self):
        with database.connect() as c:
            before = {table:[tuple(r) for r in c.execute(f'SELECT * FROM {table}')] for table in
                      ('candidates','companies','skills','profile_materials','swipe_decisions','notifications','match_audit')}
        accepted,result = await self.completed()  # No account/password/cookie/CSRF/Origin.
        self.assertEqual((await self.request('GET',accepted['status_url']))[1]['status'],'completed')
        self.assertTrue(result['analysis']['findings'])
        self.assertTrue(all(f['review_status']=='unreviewed' for f in result['analysis']['findings']))
        status,data,headers = await self.request('GET',self.base+'/employers/1/findings')
        self.assertEqual((status,data['status']),(200,'completed'))
        self.assertEqual(data['analyses'][0],result['analysis'])
        self.assertEqual(headers[b'cache-control'],b'no-store')
        self.assertEqual((await self.request('POST',self.start))[1]['job_id'],accepted['job_id'])
        self.assertEqual((await self.request('GET',self.base+f'/materials/{self.material}'))[1]['job']['id'],accepted['job_id'])
        with database.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM evidence_analysis_jobs').fetchone()[0],1)
            for table,rows in before.items():self.assertEqual([tuple(r) for r in c.execute(f'SELECT * FROM {table}')],rows)

    async def test_other_candidates_materials_jobs_and_grants_are_rejected(self):
        for candidate in (1,402,406,411,483,900002,2**63-1):
            root=f'/api/ai-demo/candidates/{candidate}'
            self.assertEqual((await self.request('POST',root+f'/materials/{self.material}/analysis'))[0],403)
            self.assertEqual((await self.request('GET',root+'/employers/1/findings'))[0],403)
            self.assertEqual((await self.request('GET',root+'/analysis-jobs/'+'a'*32+'/result'))[0],403)
        self.assertEqual((await self.request('POST',self.base+'/materials/999999/analysis'))[0],403)
        self.assertEqual((await self.request('GET',self.base+'/employers/2/findings'))[0],403)
        for identifier in ('a'*32,demo_boundary.JOB_PREFIX+'b'*16):
            self.assertEqual((await self.request('GET',self.base+'/analysis-jobs/'+identifier+'/result'))[0],404)
        for body in ({'url':'http://localhost/private'},{'material_id':1},{'file_path':'/tmp/private'},{'top_k':3},{'employer_grants':{'1':[402]}}):
            self.assertEqual((await self.request('POST',self.start,body=body))[0],422)
        self.assertEqual((await self.request('POST',self.start+'?url=http://localhost/private'))[0],422)
        # The old protected path is not made public, even for this candidate.
        self.assertEqual((await self.request('POST',f'/api/candidates/900001/materials/{self.material}/analysis'))[0],403)
        self.assertEqual((await self.request('GET','/api/companies/1/candidates/900001/evidence-analysis'))[0],403)
        semantic_matching.EmbeddingClient.return_value.check_ready.assert_not_called()

    async def test_disabled_or_broadened_configuration_fails_closed(self):
        for settings in ({'TALENTMATCH_AI_PUBLIC_DEMO':'0'},{'TALENTMATCH_AI_SYNTHETIC_DEMO':'0'},
                         {'TALENTMATCH_AI_SYNTHETIC_CANDIDATES':'900001,402'}):
            with patch.dict('os.environ',settings):
                self.assertEqual((await self.request('POST',self.start))[0],404)

    async def test_public_demo_needs_no_session_passwords_csrf_or_employer_grants(self):
        with patch.dict('os.environ',TALENTMATCH_AI_DEMO_ACCOUNTS='',TALENTMATCH_AI_SESSION_SECRET='',TALENTMATCH_AI_DEMO_TOKEN='',TALENTMATCH_AI_EMPLOYER_ACCESS='{"1":[402,406]}'):
            await self.completed()
            self.assertEqual((await self.request('GET',self.base+'/employers/1/findings'))[0],200)
            self.assertEqual((await self.request('GET','/api/ai-demo/candidates/402/employers/1/findings'))[0],403)

    async def test_changed_project_or_additional_upload_disables_public_access(self):
        with database.connect() as c:
            c.execute('UPDATE profile_materials SET description=? WHERE id=?',('UNAPPROVED_PRIVATE_TEXT',self.material))
        for method,path in (('POST',self.start),('GET',self.base+'/employers/1/findings')):
            status,data,_=await self.request(method,path)
            self.assertEqual(status,403);self.assertNotIn('UNAPPROVED_PRIVATE_TEXT',json.dumps(data))
        with database.connect() as c:
            c.execute('UPDATE profile_materials SET description=? WHERE id=?',(synthetic_demo.PROJECT['description'],self.material))
            c.execute("INSERT INTO profile_materials(candidate_id,category,title,content,filename,content_type) VALUES(900001,'cv','Unapproved',?,'private.pdf','application/pdf')",(b'SYNTHETIC_PRIVATE_BYTES',))
        self.assertEqual((await self.request('POST',self.start))[0],403)
        semantic_matching.EmbeddingClient.return_value.check_ready.assert_not_called()

    async def test_worker_rechecks_material_and_never_analyzes_changed_text(self):
        entered,release=threading.Event(),threading.Event()
        def execute(job,*_):
            entered.set(); release.wait(3)
            return {'report':jobs.analyze_material(job,9999999999)}
        self.manager.execute=execute
        try:
            self.assertEqual((await self.request('POST',self.start))[0],202)
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            with database.connect() as c:c.execute('UPDATE profile_materials SET title=? WHERE id=?',('Changed',self.material))
        finally:release.set()
        await asyncio.to_thread(self.manager.future.result,3)
        semantic_matching.EmbeddingClient.return_value.check_ready.assert_not_called()
        with database.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM evidence_analysis_jobs').fetchone()[0],'failed')
            self.assertEqual(c.execute('SELECT count(*) FROM evidence_analysis_runs').fetchone()[0],0)

    async def test_persistence_rechecks_material_after_inference(self):
        def execute(job,*_):
            report=jobs.analyze_material(job,9999999999)
            with database.connect() as c:c.execute('UPDATE profile_materials SET description=? WHERE id=?',('Changed after inference',self.material))
            return {'report':report}
        self.manager.execute=execute
        self.assertEqual((await self.request('POST',self.start))[0],202)
        await asyncio.to_thread(self.manager.future.result,3)
        with database.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM evidence_analysis_runs').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT status FROM evidence_analysis_jobs').fetchone()[0],'failed')

    async def test_tampered_stored_excerpt_is_never_shared(self):
        accepted,_=await self.completed()
        with database.connect() as c:
            source=c.execute('SELECT id,length(excerpt) FROM evidence_sources LIMIT 1').fetchone()
            c.execute('UPDATE evidence_sources SET excerpt=? WHERE id=?',('X'*source[1],source[0]))
        self.assertEqual((await self.request('GET',accepted['result_url']))[0],403)
        self.assertEqual((await self.request('GET',self.base+'/employers/1/findings'))[0],403)

    async def test_unavailable_model_returns_failure_and_retry_is_bounded(self):
        self.manager.execute=lambda *_: {'error':'unavailable'}
        status,accepted,_=await self.request('POST',self.start)
        self.assertEqual(status,202)
        await asyncio.to_thread(self.manager.future.result,3)
        status,data,_=await self.request('GET',accepted['result_url'])
        self.assertEqual((status,data['job']['status'],data['job']['error_code']),(200,'failed','unavailable'))
        self.assertIsNone(data['analysis'])
        self.assertEqual((await self.request('POST',self.start))[0],429)

    async def test_unrelated_active_job_is_not_recovered_or_modified(self):
        with database.connect() as c:
            c.execute("INSERT INTO evidence_analysis_jobs(id,candidate_id,material_id,top_k,status,lease_deadline) VALUES(?,900002,1,3,'running',0)",('f'*32,))
        with database.connect() as c:before='\n'.join(c.iterdump())
        self.assertEqual((await self.request('POST',self.start))[0],429)
        with database.connect() as c:self.assertEqual('\n'.join(c.iterdump()),before)

    async def test_hosted_application_password_still_protects_public_demo(self):
        with patch.dict('os.environ',TALENTMATCH_HOSTED_DEMO='1',TALENTMATCH_DEMO_AUTH_ENABLED='true',TALENTMATCH_DEMO_PASSWORD='synthetic-hosted-test-only'):
            self.app.add_middleware(DemoAuthMiddleware)
            self.assertEqual((await self.request('POST',self.start))[0],401)
            authorization=base64.b64encode(b'demo:synthetic-hosted-test-only')
            await self.completed(headers=[(b'authorization',b'Basic '+authorization)])
