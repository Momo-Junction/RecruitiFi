"""Fabricated new subject only; disposable SQLite and mocked inference, no network."""
import asyncio
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from . import database, demo_accounts
from .seed_data import SKILLS
from .evidence import api, employer_api, jobs, sessions, semantic_matching, synthetic_demo


class SyntheticAIDemoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory(prefix='recruitifi-new-synthetic-')
        self.addCleanup(directory.cleanup)
        patches=[patch.object(database,'DB_PATH',Path(directory.name)/'test.sqlite3'),
            patch.dict('os.environ',{
                'TALENTMATCH_AI_SYNTHETIC_DEMO':'1',
                'TALENTMATCH_AI_FETCH_PUBLIC_PROFILES':'0',
                'TALENTMATCH_AI_SYNTHETIC_CANDIDATES':'900001',
                'TALENTMATCH_AI_DEMO_TOKEN':'synthetic-only-test-operator-token-123456',
                'TALENTMATCH_AI_SESSION_SECRET':'synthetic-only-test-signing-secret-123456',
                'TALENTMATCH_AI_DEMO_ACCOUNTS':json.dumps({'talent-ai-001':'synthetic-talent-test-password','employer-001':'synthetic-employer-test-password'}),
                'TALENTMATCH_AI_EMPLOYER_ACCESS':'{"1":[900001]}'}),
            patch.object(socket.socket,'connect',side_effect=AssertionError('No network permitted')),
            patch.object(socket,'getaddrinfo',side_effect=AssertionError('No DNS permitted'))]
        for guard in patches:
            guard.start();self.addCleanup(guard.stop)
        encoder=patch.object(semantic_matching,'EmbeddingClient')
        model=encoder.start().return_value;self.addCleanup(encoder.stop)
        model.embed.side_effect=lambda texts,**_: [[1.0]+[0.0]*383 for _ in texts]
        with database.connect() as c:
            c.executescript(database.SCHEMA_PATH.read_text())
            c.executemany('INSERT INTO skills VALUES(?,?,?,?)',[(i,f'urn:synthetic:{i}',name,category) for i,(name,category) in enumerate(SKILLS,1)])
            c.execute('INSERT INTO companies VALUES(1,?,?,?,?,?,?,?,?)',('Fabricated company','IT','S1',0,'English',50,'[]','[]'))
            c.execute('INSERT INTO candidates VALUES(900002,?,?,?,?,?,?,?,?)',('OTHER-SYNTHETIC','Fabricated other','other@example.invalid',0,0,'{"English":"B2"}',0,'[]'))
            c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(900002,'project','Other fabricated evidence','Preserve this fixture','https://example.invalid/other')")
            c.execute("INSERT INTO swipe_decisions VALUES(900002,1,'talent','like')")
            c.execute("INSERT INTO notifications(candidate_id,company_id,recipient,kind) VALUES(900002,1,'talent','interest')")
            c.execute("INSERT INTO match_audit(source,company_name,inputs,result) VALUES('synthetic','Fabricated company','{}','{\"total_score\":31}')")
        sessions._attempts.clear()
        self.app=FastAPI()
        for router in (api.router,sessions.router,employer_api.router,demo_accounts.router):self.app.include_router(router)
        self.manager=jobs.AnalysisManager(execute=lambda job,*_: {'report':jobs.analyze_material(job,time.time()+30)})
        self.app.state.evidence_jobs=self.manager

    async def asyncTearDown(self):
        await asyncio.to_thread(self.manager.close)

    async def request(self,method,path,body=None,headers=()):
        messages=[];payload=json.dumps(body).encode() if body is not None else b''
        async def receive():return {'type':'http.request','body':payload,'more_body':False}
        async def send(message):messages.append(message)
        await self.app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1',
            'method':method,'path':path,'raw_path':path.encode(),'root_path':'','query_string':b'',
            'scheme':'https','server':('test',443),'client':('127.0.0.1',1),
            'headers':[(b'content-type',b'application/json'),*headers]},receive,send)
        return messages[0]['status'],json.loads(b''.join(m.get('body',b'') for m in messages)),dict(messages[0]['headers'])

    async def login(self,identity,password):
        status,data,headers=await self.request('POST','/api/evidence-session',{'account':identity,'password':password},[(b'origin',b'https://test')])
        self.assertEqual(status,200)
        return [(b'cookie',headers[b'set-cookie'].split(b';')[0]),(b'origin',b'https://test'),(b'x-recruitifi-csrf',data['csrf'].encode())]

    async def test_additive_provisioning_preserves_existing_rows_and_account_mappings(self):
        with database.connect() as c:
            baseline={name:[tuple(r) for r in c.execute(f'SELECT * FROM {name}')] for name in ('candidates','skills','companies','swipe_decisions','notifications','profile_materials','match_audit')}
            material=synthetic_demo.provision(c)
            for name,rows in baseline.items():
                if name=='candidates':actual=[tuple(r) for r in c.execute('SELECT * FROM candidates WHERE id!=900001')]
                elif name=='profile_materials':actual=[tuple(r) for r in c.execute('SELECT * FROM profile_materials WHERE id!=?',(material,))]
                else:actual=[tuple(r) for r in c.execute(f'SELECT * FROM {name}')]
                self.assertEqual(actual,rows)
            before='\n'.join(c.iterdump())
            with self.assertRaisesRegex(ValueError,'occupied'):synthetic_demo.provision(c)
            self.assertEqual('\n'.join(c.iterdump()),before)
            self.assertEqual(c.execute('SELECT skills FROM candidates WHERE id=900001').fetchone()[0],'[]')
        self.assertEqual([demo_accounts.BY_ID[f'talent-{i:03}']['candidate_id'] for i in range(1,16)],list(demo_accounts.TALENT_IDS))
        self.assertEqual(demo_accounts.BY_ID['employer-001']['company_id'],1)
        catalog=(await self.request('GET','/api/demo/accounts'))[1]['accounts']
        self.assertTrue(next(a for a in catalog if a['demo_account_id']=='talent-ai-001')['available'])

    async def test_new_subject_analysis_and_explicit_employer_sharing(self):
        with database.connect() as c:material=synthetic_demo.provision(c)
        talent=await self.login('talent-ai-001','synthetic-talent-test-password')
        start=f'/api/candidates/900001/materials/{material}/analysis'
        self.assertEqual((await self.request('POST',start))[0],403)
        self.assertEqual((await self.request('POST',start,headers=talent[:-1]))[0],403)
        status,accepted,_=await self.request('POST',start,headers=talent)
        self.assertEqual(status,202)
        for _ in range(100):
            status,result,_=await self.request('GET',accepted['result_url'],headers=talent)
            if status==200:break
            await asyncio.sleep(.01)
        self.assertEqual(result['job']['status'],'completed')
        self.assertTrue(all(f['review_status']=='unreviewed' for f in result['analysis']['findings']))
        for forbidden in (402,406,900002):
            self.assertEqual((await self.request('POST',f'/api/candidates/{forbidden}/materials/{material}/analysis',headers=talent))[0],403)
        employer=await self.login('employer-001','synthetic-employer-test-password')
        path='/api/companies/1/candidates/900001/evidence-analysis'
        status,shared,_=await self.request('GET',path,headers=employer)
        self.assertEqual((status,shared['status']),(200,'completed'))
        self.assertTrue(shared['analyses'])
        for forbidden in (402,406,900002):
            self.assertEqual((await self.request('GET',f'/api/companies/1/candidates/{forbidden}/evidence-analysis',headers=employer))[0],403)
        self.assertEqual((await self.request('GET','/api/companies/2/candidates/900001/evidence-analysis',headers=employer))[0],403)
        self.assertEqual((await self.request('POST',start,headers=employer))[0],403)
        with patch.dict('os.environ',TALENTMATCH_AI_EMPLOYER_ACCESS='{}'):
            self.assertIn((await self.request('GET',path,headers=employer))[0],(403,404))
        with database.connect() as c:
            self.assertEqual(c.execute('SELECT skills FROM candidates WHERE id=900001').fetchone()[0],'[]')

    async def test_material_failure_rolls_back_new_candidate(self):
        # Fail insertion without touching any existing record.
        with database.connect() as c:
            c.execute("CREATE TRIGGER synthetic_test_failure BEFORE INSERT ON profile_materials BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
            c.commit()
            before='\n'.join(c.iterdump())
            with self.assertRaises(sqlite3.IntegrityError):synthetic_demo.provision(c)
            self.assertEqual('\n'.join(c.iterdump()),before)
