import asyncio
import json
import unittest
from unittest.mock import patch
from . import database,test_synthetic_ai_demo as fixtures
from .evidence import profile_matching,synthetic_demo
from .test_job_relevance import vector
from .evidence.embedding_client import EmbeddingServiceError


class ProfileMatchingTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown=fixtures.SyntheticAIDemoTests.asyncTearDown
    request=fixtures.SyntheticAIDemoTests.request
    login=fixtures.SyntheticAIDemoTests.login

    def setUp(self):
        fixtures.SyntheticAIDemoTests.setUp(self)
        flag=patch.dict('os.environ',TALENTMATCH_AI_JOB_MATCHING='1');flag.start();self.addCleanup(flag.stop)
        model=patch.object(profile_matching,'EmbeddingClient');client=model.start().return_value;self.addCleanup(model.stop)
        client.embed.side_effect=lambda texts,**_: [vector(1 if t=='React' else 0) for t in texts]
        self.app.include_router(profile_matching.router)
        with database.connect() as c:
            synthetic_demo.provision(c)
            for identifier,skill in ((501,1),(502,3)):
                c.execute('INSERT INTO job_openings VALUES(?,1,?,?,?, ?,?,1)',(identifier,'Fabricated job','it','Fictional description',json.dumps([{'skill_id':skill,'weight':70}]),'[]'))

    async def analyze(self):
        talent=await self.login('talent-ai-001','synthetic-talent-test-password')
        status,_,_=await self.request('POST','/api/ai-matches/profiles/900001/analyze',headers=talent)
        self.assertEqual(status,202)
        await asyncio.to_thread(self.manager.future.result,5)
        status,data,_=await self.request('GET','/api/ai-matches/profiles/900001',headers=talent)
        self.assertEqual(status,200)
        return talent,data

    async def test_real_pipeline_cache_is_job_specific_and_private(self):
        talent,data=await self.analyze()
        self.assertEqual(data['status'],'completed')
        self.assertEqual(data['matches']['501']['score'],100)
        self.assertEqual(data['matches']['502']['score'],0)
        self.assertEqual((await self.request('GET','/api/ai-matches/profiles/900001'))[0],403)
        self.assertEqual((await self.request('GET','/api/ai-matches/profiles/900002',headers=talent))[0],403)
        employer=await self.login('employer-001','synthetic-employer-test-password')
        self.assertEqual((await self.request('GET','/api/ai-matches/profiles/900001',headers=employer))[1]['matches'],data['matches'])
        with patch.dict('os.environ',TALENTMATCH_AI_EMPLOYER_ACCESS='{}'):
            self.assertIn((await self.request('GET','/api/ai-matches/profiles/900001',headers=employer))[0],(403,404))
        self.assertEqual((await self.request('POST','/api/ai-matches/profiles/900001/analyze',headers=employer))[0],403)

    async def test_job_and_evidence_changes_invalidate_results(self):
        talent,_=await self.analyze()
        with database.connect() as c:c.execute("UPDATE job_openings SET description='Changed fictional job' WHERE id=501")
        self.assertEqual((await self.request('GET','/api/ai-matches/profiles/900001',headers=talent))[1]['status'],'stale')
        with database.connect() as c:c.execute("UPDATE profile_materials SET description='Unapproved edit' WHERE candidate_id=900001")
        result=(await self.request('GET','/api/ai-matches/profiles/900001',headers=talent))[1]
        self.assertEqual(result['matches'],{})
        self.assertEqual((await self.request('POST','/api/ai-matches/profiles/900001/analyze',headers=talent))[0],403)

    async def test_model_failure_never_produces_a_fallback_score(self):
        profile_matching.EmbeddingClient.return_value.check_ready.side_effect=EmbeddingServiceError('unavailable')
        _,data=await self.analyze()
        self.assertEqual(data['status'],'unavailable')
        self.assertEqual(data['matches'],{})


class ConsentedProfileTests(ProfileMatchingTests):
    """All records are fabricated in a temporary database, including account 001."""
    def setUp(self):
        super().setUp()
        flag=patch.dict('os.environ',{
            'TALENTMATCH_AI_CONSENTED_MODE':'1','TALENTMATCH_AI_SYNTHETIC_DEMO':'0',
            'TALENTMATCH_AI_CANDIDATES':'402,900001',
            'TALENTMATCH_AI_DEMO_ACCOUNTS':json.dumps({'talent-001':'fabricated-owner-test-password','talent-ai-001':'synthetic-talent-test-password','employer-001':'synthetic-employer-test-password'})})
        flag.start();self.addCleanup(flag.stop)
        with database.connect() as c:
            c.execute('INSERT INTO candidates VALUES(402,?,?,?,?,?,?,?,?)',('TEST-ONLY','Fabricated owner','test@example.invalid',0,0,'{}',0,'[]'))
            self.material=c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(402,'project','Fabricated Python API','Python API synthetic test only','https://example.invalid/project')").lastrowid
            self.other=c.execute('SELECT id FROM profile_materials WHERE candidate_id=900002').fetchone()[0]
        self.path='/api/ai-matches/profiles/402'

    async def consent(self,headers,share=False,material=None):
        return await self.request('POST',self.path+'/consent',{'material_ids':[material or self.material],'confirm':True,'share_with_employer_001':share},headers)

    async def test_existing_talent_requires_own_material_consent_and_csrf(self):
        owner=await self.login('talent-001','fabricated-owner-test-password')
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],403)
        self.assertEqual((await self.consent(owner[:-1]))[0],403)
        self.assertEqual((await self.consent(owner,material=self.other))[0],403)
        self.assertEqual((await self.consent(owner))[0],200)
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
        await asyncio.to_thread(self.manager.future.result,5)
        response=await self.request('GET',self.path,headers=owner)
        self.assertEqual(response[1]['status'],'completed')
        with database.connect() as c:
            self.assertEqual(c.execute('SELECT skills FROM candidates WHERE id=402').fetchone()[0],'[]')
            c.execute("UPDATE profile_materials SET description='Changed synthetic content' WHERE id=?",(self.material,))
        self.assertEqual((await self.request('GET',self.path,headers=owner))[1]['matches'],{})
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],403)

    async def test_sharing_is_explicit_revocable_and_cannot_be_overridden_by_grants(self):
        owner=await self.login('talent-001','fabricated-owner-test-password')
        employer=await self.login('employer-001','synthetic-employer-test-password')
        self.assertEqual((await self.request('GET',self.path,headers=employer))[0],403)
        self.assertEqual((await self.consent(owner,share=True))[0],200)
        self.assertEqual((await self.request('GET',self.path,headers=employer))[0],200)
        self.assertEqual((await self.consent(owner,share=False))[0],200)
        with patch.dict('os.environ',TALENTMATCH_AI_EMPLOYER_ACCESS='{"1":[402,900001]}'):
            self.assertEqual((await self.request('GET',self.path,headers=employer))[0],403)
        self.assertEqual((await self.consent(employer,share=True))[0],403)
        other=await self.login('talent-ai-001','synthetic-talent-test-password')
        self.assertEqual((await self.request('GET',self.path,headers=other))[0],403)
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=other))[0],403)

    def test_all_fifteen_existing_talent_aliases_can_be_configured_without_public_access(self):
        from . import demo_accounts
        from .evidence import jobs,sessions
        identities=[*demo_accounts.TALENT_IDS,900001]
        accounts={f'talent-{i:03}':f'fabricated-distinct-password-{i}' for i in range(1,16)}
        accounts.update({'talent-ai-001':'synthetic-talent-test-password','employer-001':'synthetic-employer-test-password'})
        with patch.dict('os.environ',TALENTMATCH_AI_CANDIDATES=','.join(map(str,identities)),TALENTMATCH_AI_DEMO_ACCOUNTS=json.dumps(accounts)):
            self.assertEqual(jobs.configuration()[1],set(identities))
            self.assertEqual(len(sessions.settings()[1]),17)
            self.assertFalse(jobs.allowed(900002))

    async def test_invalid_github_host_is_rejected_with_actionable_error(self):
        with database.connect() as c:
            c.execute("UPDATE profile_materials SET category='github',url='https://github.com.evil.invalid/FictionalOwner' WHERE id=?",(self.material,))
        owner=await self.login('talent-001','fabricated-owner-test-password')
        status,error,_=await self.consent(owner)
        self.assertEqual(status,422)
        self.assertIn('HTTPS GitHub',error['detail'])
        with database.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM evidence_analysis_jobs').fetchone()[0],0)

    async def test_all_selected_materials_are_validated_not_only_first(self):
        with database.connect() as c:
            invalid=c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(402,'github','Synthetic profile','','https://github.com.evil.invalid/FictionalOwner')").lastrowid
        owner=await self.login('talent-001','fabricated-owner-test-password')
        status,_,_=await self.request('POST',self.path+'/consent',{'material_ids':[self.material,invalid],'confirm':True},owner)
        self.assertEqual(status,422)

    async def test_expired_worker_lease_is_recovered_by_profile_polling(self):
        owner=await self.login('talent-001','fabricated-owner-test-password')
        await self.consent(owner)
        with database.connect() as c:
            c.execute("INSERT INTO evidence_analysis_jobs(id,candidate_id,material_id,top_k,status,lease_deadline) VALUES(?,402,?,3,'running',0)",('a'*32,self.material))
        status,data,_=await self.request('GET',self.path,headers=owner)
        self.assertEqual(status,200)
        self.assertEqual(data['status'],'unavailable')
        self.assertEqual(data['reason'],'worker_interrupted')
        self.assertIn('retry',data['detail'])

    def test_invalid_pdfs_fail_before_model_and_cv_labels_are_not_embedded(self):
        from .test_evidence import synthetic_pdf
        row={'id':99,'candidate_id':402,'category':'cv','title':'React proficient','description':'Misleading label','url':None,'filename':'synthetic.pdf','content_type':'application/pdf','content':synthetic_pdf(image_only=True)}
        for blob,code in ((row['content'],'no_extractable_text'),(b'%PDF-broken','malformed_pdf'),(synthetic_pdf(password='test'),'encrypted_pdf')):
            with self.assertRaises(profile_matching.AnalysisInputError) as error:
                profile_matching.extracted({**row,'content':blob})
            self.assertEqual(error.exception.code,code)
        result=profile_matching.extracted({**row,'content':synthetic_pdf()})
        self.assertEqual(result['project_title'],'')
        self.assertEqual(result['project_description'],'')
        self.assertIn('Python',result['pdf_text'])

    async def test_selected_github_repositories_share_one_retrieval_budget(self):
        from .evidence import jobs
        import time
        with database.connect() as c:
            c.execute("UPDATE profile_materials SET category='github',url='https://github.com/Synthetic/One' WHERE id=?",(self.material,))
            second=c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(402,'github','Synthetic Two','Fabricated Python API','https://github.com/Synthetic/Two')").lastrowid
        owner=await self.login('talent-001','fabricated-owner-test-password')
        self.assertEqual((await self.request('POST',self.path+'/consent',{'material_ids':[self.material,second],'confirm':True},owner))[0],200)
        def retrieved(repositories,**_):
            return [{'repository':repo,'retrieval_status':'retrieved','tree_sha':'a'*40,'http_status':200,'skipped':[],
                'files':[{'path':'README.md','text':'Fabricated Python API','source_reference':f"https://api.github.com/repos/{repo['owner']}/{repo['repository']}/git/blobs/"+'b'*40,'blob_sha':'b'*40,'decoded_bytes':21,'untrusted':True}]} for repo in repositories]
        with patch.object(profile_matching,'fetch_github_repositories',side_effect=retrieved) as fetch:
            report=jobs.analyze_material({'candidate_id':402,'material_id':self.material,'top_k':3},time.time()+30)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(len(fetch.call_args.args[0]),2)
        self.assertEqual(report['ai_job_matches']['status'],'completed')

    async def test_every_non_github_resource_category_reaches_analysis_and_storage(self):
        from .test_evidence import synthetic_pdf
        owner=await self.login('talent-001','fabricated-owner-test-password')
        for category in ('cv','project','certificate','research','linkedin','website'):
            with self.subTest(category=category):
                with database.connect() as c:
                    if category in ('linkedin','website'):
                        c.execute('UPDATE profile_materials SET category=?,url=?,filename=NULL,content_type=NULL,content=NULL,description=? WHERE id=?',(category,'https://example.invalid/synthetic','Fabricated Python REST API description',self.material))
                    else:
                        c.execute("UPDATE profile_materials SET category=?,url=NULL,filename='synthetic.pdf',content_type='application/pdf',content=?,description='Fabricated Python API' WHERE id=?",(category,synthetic_pdf(),self.material))
                self.assertEqual((await self.consent(owner))[0],200)
                self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
                await asyncio.to_thread(self.manager.future.result,5)
                data=(await self.request('GET',self.path,headers=owner))[1]
                self.assertEqual(data['status'],'completed',data)
                self.assertEqual(data['sources'][0]['category'],category)
                self.assertEqual(data['sources'][0]['content_status'],'saved_metadata_only' if category in ('linkedin','website') else 'pdf_text')

    async def test_image_descriptions_are_analyzed_without_claiming_ocr(self):
        owner=await self.login('talent-001','fabricated-owner-test-password')
        with database.connect() as c:
            c.execute("UPDATE profile_materials SET category='certificate',url=NULL,filename='synthetic.png',content_type='image/png',content=?,description='Fabricated Python coursework' WHERE id=?",(b'\x89PNG\r\n\x1a\n synthetic only',self.material))
        self.assertEqual((await self.consent(owner))[0],200)
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
        await asyncio.to_thread(self.manager.future.result,5)
        data=(await self.request('GET',self.path,headers=owner))[1]
        self.assertEqual(data['status'],'completed',data)
        self.assertEqual(data['sources'][0]['content_status'],'saved_metadata_only')
        with database.connect() as c:c.execute("UPDATE profile_materials SET description='' WHERE id=?",(self.material,))
        self.assertEqual((await self.consent(owner))[0],422)

    async def test_selected_materials_each_receive_a_text_budget(self):
        owner=await self.login('talent-001','fabricated-owner-test-password')
        with database.connect() as c:
            c.execute('UPDATE profile_materials SET description=? WHERE id=?',('Python '*200,self.material))
            second=c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(402,'research','Synthetic research','React','https://example.invalid/research')").lastrowid
        self.assertEqual((await self.request('POST',self.path+'/consent',{'material_ids':[self.material,second],'confirm':True},owner))[0],200)
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
        await asyncio.to_thread(self.manager.future.result,5)
        data=(await self.request('GET',self.path,headers=owner))[1]
        self.assertEqual(data['status'],'completed')
        self.assertEqual(data['matches']['502']['requirements'][0]['material_id'],second)
        self.assertEqual(data['matches']['502']['score'],100)

    async def test_skill_edits_invalidate_ai_and_remain_claims_without_evidence(self):
        from .profile_materials import router
        self.app.include_router(router)
        owner=await self.login('talent-001','fabricated-owner-test-password')
        await self.consent(owner)
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
        await asyncio.to_thread(self.manager.future.result,5)
        before=(await self.request('GET',self.path,headers=owner))[1]
        self.assertEqual(before['matches']['502']['requirements'][0]['status'],'missing')
        self.assertEqual((await self.request('PUT','/api/candidates/402/skills',[3],owner))[0],200)
        self.assertEqual((await self.request('GET',self.path,headers=owner))[1]['status'],'stale')
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
        await asyncio.to_thread(self.manager.future.result,5)
        after=(await self.request('GET',self.path,headers=owner))[1]
        self.assertEqual(after['matches']['502']['requirements'][0]['status'],'claimed_only')
        self.assertEqual(after['matches']['502']['score'],before['matches']['502']['score'])

    async def test_fictional_account_can_select_new_resources_in_consented_mode(self):
        from .test_evidence import synthetic_pdf
        owner=await self.login('talent-ai-001','synthetic-talent-test-password')
        with database.connect() as c:
            new=c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,filename,content_type,content) VALUES(900001,'certificate','Synthetic course','Fabricated Python course','fixture.pdf','application/pdf',?)",(synthetic_pdf(),)).lastrowid
        path='/api/ai-matches/profiles/900001'
        self.assertEqual((await self.request('POST',path+'/consent',{'material_ids':[new],'confirm':True},owner))[0],200)
        self.assertEqual((await self.request('POST',path+'/analyze',headers=owner))[0],202)
        await asyncio.to_thread(self.manager.future.result,5)
        data=(await self.request('GET',path,headers=owner))[1]
        self.assertEqual(data['status'],'completed',data)
        self.assertEqual([s['material_id'] for s in data['sources']],[new])

    async def test_empty_linkedin_and_github_profiles_do_not_block_valid_evidence(self):
        owner=await self.login('talent-001','fabricated-owner-test-password')
        with database.connect() as c:
            linkedin=c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(402,'linkedin','LinkedIn','','https://www.linkedin.com/in/synthetic-only')").lastrowid
            github=c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(402,'github','GitHub','','https://github.com/FictionalOwner')").lastrowid
        path=self.path
        self.assertEqual((await self.request('POST',path+'/consent',{'material_ids':[linkedin,github,self.material],'confirm':True},owner))[0],200)
        with patch.object(profile_matching,'fetch_github_repositories',side_effect=AssertionError('Profiles must not be fetched')):
            self.assertEqual((await self.request('POST',path+'/analyze',headers=owner))[0],202)
            await asyncio.to_thread(self.manager.future.result,5)
        data=(await self.request('GET',path,headers=owner))[1]
        self.assertEqual(data['status'],'completed',data)
        self.assertEqual({s['material_id'] for s in data['sources'] if s['content_status']=='not_analyzed'},{linkedin,github})
        self.assertTrue(data['matches'])

    async def test_github_profile_descriptions_are_analyzed_without_fetching(self):
        owner=await self.login('talent-001','fabricated-owner-test-password')
        with database.connect() as c:
            c.execute("UPDATE profile_materials SET category='github',url='https://github.com/FictionalOwner',description='Fabricated Python API' WHERE id=?",(self.material,))
        self.assertEqual((await self.consent(owner))[0],200)
        with patch.object(profile_matching,'fetch_github_repositories',side_effect=AssertionError('No profile fetching')):
            self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
            await asyncio.to_thread(self.manager.future.result,5)
        data=(await self.request('GET',self.path,headers=owner))[1]
        self.assertEqual(data['status'],'completed',data)
        self.assertEqual(data['sources'][0]['content_status'],'saved_metadata_only')
        with database.connect() as c:c.execute("UPDATE profile_materials SET description='' WHERE id=?",(self.material,))
        self.assertEqual((await self.consent(owner))[0],200)
        status,error,_=await self.request('POST',self.path+'/analyze',headers=owner)
        self.assertEqual(status,422)
        self.assertIn('no analyzable text',error['detail'])

    async def test_link_description_edits_require_owner_csrf_and_renewed_consent(self):
        owner=await self.login('talent-001','fabricated-owner-test-password')
        other=await self.login('talent-ai-001','synthetic-talent-test-password')
        path=f'{self.path}/materials/{self.material}/description'
        self.assertEqual((await self.request('PATCH',path,{'description':'Synthetic edited project'},owner[:-1]))[0],403)
        self.assertEqual((await self.request('PATCH',path,{'description':'Synthetic edited project'},other))[0],403)
        await self.consent(owner)
        self.assertEqual((await self.request('PATCH',path,{'description':'Synthetic edited project'},owner))[0],200)
        self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],403)
        self.assertEqual((await self.request('PATCH',path,{'description':'x'*1501},owner))[0],422)
        self.assertEqual((await self.request('PATCH',path,{'description':'Synthetic','url':'https://evil.invalid'},owner))[0],422)

    async def test_public_profile_content_is_retrieved_without_manual_descriptions(self):
        from .evidence import public_profiles
        owner=await self.login('talent-001','fabricated-owner-test-password')
        flag=patch.dict('os.environ',TALENTMATCH_AI_FETCH_PUBLIC_PROFILES='1')
        with flag:
            for category,url in (('github','https://github.com/SyntheticOwner'),('linkedin','https://www.linkedin.com/in/synthetic-only')):
                with self.subTest(category=category),database.connect() as c:
                    c.execute("UPDATE profile_materials SET category=?,url=?,description='' WHERE id=?",(category,url,self.material))
                self.assertEqual((await self.consent(owner))[0],200)
                with patch.object(public_profiles,'fetch_profile',return_value={'status':'retrieved','text':'Fabricated Python API developer','references':[url],'untrusted':True}) as fetch:
                    self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
                    await asyncio.to_thread(self.manager.future.result,5)
                data=(await self.request('GET',self.path,headers=owner))[1]
                self.assertEqual(data['status'],'completed',data)
                self.assertEqual(fetch.call_count,1)
                self.assertTrue(data['public_profile_retrieval_enabled'])
                self.assertIn(data['sources'][0]['content_status'],('public_github_metadata','public_profile_text'))
                with database.connect() as c:
                    self.assertEqual(c.execute('SELECT description FROM profile_materials WHERE id=?',(self.material,)).fetchone()[0],'')
                    self.assertEqual(c.execute('SELECT source_type FROM evidence_sources ORDER BY id DESC LIMIT 1').fetchone()[0],'public_'+category+'_profile')

    async def test_blocked_linkedin_does_not_become_evidence_or_block_other_sources(self):
        from .evidence import public_profiles
        owner=await self.login('talent-001','fabricated-owner-test-password')
        with database.connect() as c:
            linkedin=c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(402,'linkedin','LinkedIn','','https://www.linkedin.com/in/synthetic-only')").lastrowid
        with patch.dict('os.environ',TALENTMATCH_AI_FETCH_PUBLIC_PROFILES='1'),patch.object(public_profiles,'fetch_profile',return_value={'status':'profile_access_blocked','text':'','references':[],'untrusted':True}):
            self.assertEqual((await self.request('POST',self.path+'/consent',{'material_ids':[linkedin,self.material],'confirm':True},owner))[0],200)
            self.assertEqual((await self.request('POST',self.path+'/analyze',headers=owner))[0],202)
            await asyncio.to_thread(self.manager.future.result,5)
            data=(await self.request('GET',self.path,headers=owner))[1]
            self.assertEqual(data['status'],'completed',data)
            self.assertTrue(data['matches'])
            blocked=next(s for s in data['sources'] if s['material_id']==linkedin)
            self.assertEqual(blocked['content_status'],'not_analyzed')
            self.assertIn('blocked',blocked['detail'])
