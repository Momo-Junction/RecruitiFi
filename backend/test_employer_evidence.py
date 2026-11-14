import json
from unittest.mock import patch
from . import test_evidence_sessions as session_fixtures
from . import test_evidence_storage as storage_fixtures
from .database import connect
from .evidence import employer_api, storage


class EmployerEvidenceTests(session_fixtures.SessionTests):
    def setUp(self):
        super().setUp()
        self.app.include_router(employer_api.router)
        config=patch.dict('os.environ',{
            'TALENTMATCH_AI_DEMO_ACCOUNTS':json.dumps({'talent-001':'synthetic-password-one','talent-002':'synthetic-password-two','employer-001':'synthetic-employer-one','employer-002':'synthetic-employer-two'}),
            'TALENTMATCH_AI_EMPLOYER_ACCESS':json.dumps({'1':[402],'2':[403]})})
        config.start();self.addCleanup(config.stop)

    async def employer_cookie(self):
        status,data=await self.request('POST','/api/evidence-session',body={'account':'employer-001','password':'synthetic-employer-one'},token=None,headers=[(b'origin',b'https://test')])
        self.assertEqual(status,200)
        self.assertEqual(data['company_id'],1)
        return [(b'cookie',self.last_headers[b'set-cookie'].split(b';')[0])]

    async def test_password_session_and_explicit_sharing_required(self):
        path='/api/companies/1/candidates/402/evidence-analysis'
        self.assertEqual((await self.request('GET',path,account='employer-001'))[0],403)
        headers=await self.employer_cookie()
        self.assertEqual((await self.request('GET',path,token=None,headers=headers))[0],200)
        for forbidden in ('/api/companies/2/candidates/403/evidence-analysis','/api/companies/1/candidates/403/evidence-analysis'):
            self.assertEqual((await self.request('GET',forbidden,token=None,headers=headers))[0],403)
        self.assertEqual((await self.start(token=None,headers=headers+[(b'origin',b'https://test')]))[0],403)
        with patch.dict('os.environ',TALENTMATCH_AI_EMPLOYER_ACCESS='{}'):
            self.assertIn((await self.request('GET',path,token=None,headers=headers))[0],(403,404))

    async def test_completed_only_redaction_status_and_read_only(self):
        with connect() as connection:
            project=storage_fixtures.EvidenceStorageTests.project(None,connection)
            storage.save_analysis(402,project,connection=connection)
            pdf=storage_fixtures.EvidenceStorageTests.project(None,connection,703)
            storage.save_analysis(402,pdf,connection=connection)
            before='\n'.join(connection.iterdump())
        headers=await self.employer_cookie()
        path='/api/companies/1/candidates/402/evidence-analysis'
        status,data=await self.request('GET',path,token=None,headers=headers)
        self.assertEqual(status,200);self.assertEqual(data['status'],'completed')
        self.assertEqual(len(data['analyses']),2)
        self.assertTrue(any(source.get('redacted') for analysis in data['analyses'] for source in analysis['sources']))
        self.assertTrue(all(f['review_status']=='unreviewed' for f in data['analyses'][0]['findings']))
        self.assertNotIn('uploaded_pdf',json.dumps(data))
        self.assertNotIn('Synthetic PDF',json.dumps(data))
        self.assertNotIn('"content":',json.dumps(data))
        for analysis in data['analyses']:
            for source in analysis['sources']:
                if source.get('redacted'):
                    self.assertEqual(source['excerpt'],'')
                    self.assertIsNone(source['source_reference'])
                    self.assertIsNone(source['file_path'])
        with connect() as connection:
            self.assertEqual('\n'.join(connection.iterdump()),before)
            connection.execute("INSERT INTO evidence_analysis_jobs(id,candidate_id,material_id,top_k,status,lease_deadline) VALUES(?,402,701,3,'failed',0)",('c'*32,))
        self.assertEqual((await self.request('GET',path,token=None,headers=headers))[1]['status'],'failed')
