"""All selectable roles use the existing signed session; disposable config only."""
import json,unittest
from unittest.mock import patch
from . import demo_accounts,test_synthetic_ai_demo as fixtures
from .evidence import sessions


class AllDemoAccountsTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown=fixtures.SyntheticAIDemoTests.asyncTearDown
    request=fixtures.SyntheticAIDemoTests.request
    login=fixtures.SyntheticAIDemoTests.login
    def setUp(self):
        fixtures.SyntheticAIDemoTests.setUp(self)
        self.accounts={alias:'synthetic-password-for-'+alias for alias in demo_accounts.BY_ID}
        config=patch.dict('os.environ',TALENTMATCH_AI_SYNTHETIC_CANDIDATES=','.join(map(str,[*demo_accounts.TALENT_IDS,900001])),TALENTMATCH_AI_DEMO_ACCOUNTS=json.dumps(self.accounts),TALENTMATCH_AI_EMPLOYER_ACCESS='{}')
        config.start();self.addCleanup(config.stop)
    async def test_every_selectable_account_authenticates_without_private_employer_grants(self):
        self.assertEqual(len(sessions.settings()[1]),22)
        for alias,expected in demo_accounts.BY_ID.items():
            sessions._attempts.clear() # Test credential coverage, not the independent rate limiter.
            headers=await self.login(alias,self.accounts[alias])
            status,identity,_=await self.request('GET','/api/evidence-session',headers=headers)
            self.assertEqual(status,200)
            self.assertEqual(identity['account_id'],alias)
            self.assertEqual(identity['role'],expected['role'])
        self.assertEqual(sessions.employer_grants(set(demo_accounts.TALENT_IDS)|{900001}),{})
    async def test_wrong_role_password_and_fake_cookie_do_not_authenticate(self):
        self.assertEqual((await self.request('POST','/api/evidence-session',{'account':'employer-005','password':self.accounts['talent-001']},[(b'origin',b'https://test')]))[0],403)
        self.assertEqual((await self.request('GET','/api/evidence-session',headers=[(b'cookie',b'recruitifi_evidence_demo=fake.fake')]))[0],403)


class ProtectedPulledTaskTests(AllDemoAccountsTests):
    def setUp(self):
        super().setUp()
        from . import database
        from .hiring_tasks import router
        self.app.include_router(router)
        with database.connect() as c:
            for i in (402,406):c.execute("INSERT INTO candidates VALUES(?,?,?,?,0,0,'{}',0,'[]')",(i,'TEST-'+str(i),'Fabricated test','test'+str(i)+'@example.invalid'))
            c.execute("INSERT INTO companies VALUES(2,'Other synthetic company','IT','S2',0,'English',50,'[]','[]')")
            c.execute("INSERT INTO swipe_decisions VALUES(402,1,'employer','like')")
    async def test_private_tasks_require_verified_owner_not_selector(self):
        employer=await self.login('employer-001',self.accounts['employer-001'])
        other=await self.login('employer-002',self.accounts['employer-002'])
        talent=await self.login('talent-001',self.accounts['talent-001'])
        stranger=await self.login('talent-002',self.accounts['talent-002'])
        body={'candidate_id':402,'company_id':1,'title':'Synthetic private task','description':'Synthetic instructions'}
        self.assertEqual((await self.request('GET','/api/hiring-tasks',headers=[(b'x-recruitifi-demo-account',b'employer-001')]))[0],403)
        self.assertEqual((await self.request('POST','/api/hiring-tasks',body,employer[:-1]))[0],403)
        status,task,_=await self.request('POST','/api/hiring-tasks',body,employer);self.assertEqual(status,201)
        path=f"/api/hiring-tasks/{task['id']}/submission/402"
        self.assertEqual((await self.request('PUT',path,{'url':'https://example.invalid/private-response'},talent))[0],200)
        self.assertEqual((await self.request('GET','/api/hiring-tasks',headers=other))[1],[])
        self.assertEqual((await self.request('GET','/api/hiring-tasks',headers=stranger))[1],[])
        self.assertEqual((await self.request('PUT',path,{'url':'https://example.invalid/tampered'},stranger))[0],403)
        self.assertEqual((await self.request('GET','/api/hiring-tasks',headers=[*other,(b'x-recruitifi-demo-account',b'employer-001')]))[0],403)
    def test_legacy_task_layouts_are_preserved_without_collision(self):
        from . import database
        from .hiring_tasks import initialize_tasks
        with database.connect() as c:
            c.execute('CREATE TABLE hiring_tasks(id INTEGER PRIMARY KEY, application_id INTEGER, instructions TEXT)')
            c.execute("INSERT INTO hiring_tasks VALUES(1,10,'Old synthetic history')")
            initialize_tasks(c)
            self.assertEqual(tuple(c.execute('SELECT * FROM hiring_tasks').fetchone()),(1,10,'Old synthetic history'))
            self.assertEqual(c.execute('SELECT count(*) FROM hiring_task_assignments').fetchone()[0],0)
    def test_compatible_task_migration_is_additive_and_repeatable(self):
        from . import database
        from .hiring_tasks import initialize_tasks
        with database.connect() as c:
            c.execute('CREATE TABLE hiring_tasks(id INTEGER PRIMARY KEY,candidate_id INTEGER,company_id INTEGER,title TEXT,description TEXT,submission_url TEXT,verified INTEGER)')
            c.execute("INSERT INTO hiring_tasks VALUES(1,402,1,'Synthetic','Old description','https://example.invalid/work',0)")
            initialize_tasks(c);initialize_tasks(c)
            self.assertEqual(c.execute('SELECT count(*) FROM hiring_task_assignments').fetchone()[0],1)
            self.assertEqual(tuple(c.execute('SELECT * FROM hiring_tasks').fetchone()),tuple(c.execute('SELECT id,candidate_id,company_id,title,description,submission_url,verified FROM hiring_task_assignments').fetchone()))
