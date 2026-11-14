"""Password-free demo mode remains opt-in, scoped and CSRF protected."""
import asyncio
import json
from unittest.mock import patch
from . import database
from . import test_profile_matching as fixtures
from .evidence import sessions


class PasswordFreeDemoTests(fixtures.ProfileMatchingTests):
    def setUp(self):
        super().setUp()
        values=json.loads(__import__('os').environ['TALENTMATCH_AI_DEMO_ACCOUNTS'])
        values['organizer-001']='fabricated-distinct-organizer-password'
        env=patch.dict('os.environ',TALENTMATCH_PASSWORD_FREE_DEMO='true',TALENTMATCH_AI_DEMO_ACCOUNTS=json.dumps(values))
        env.start();self.addCleanup(env.stop)

    async def test_password_free_talent_employer_organizer_and_cookie_flags(self):
        config=(await self.request('GET','/api/evidence-session/config'))[1]
        self.assertEqual(config,{'verified_login_required':True,'password_free_demo':True})
        for alias in ('talent-ai-001','employer-001','organizer-001'):
            status,data,headers=await self.request('POST','/api/evidence-session',{'account':alias},[(b'origin',b'https://test')])
            self.assertEqual(status,200)
            cookie=headers[b'set-cookie'];self.assertIn(b'HttpOnly',cookie);self.assertIn(b'Secure',cookie);self.assertIn(b'SameSite=strict',cookie)
            status,identity,_=await self.request('GET','/api/evidence-session',headers=[(b'cookie',cookie.split(b';')[0])])
            self.assertEqual((status,identity['account_id']),(200,alias))

    async def test_password_free_analysis_works_but_keeps_candidate_scope_and_csrf(self):
        owner=await self.login('talent-ai-001','')
        path='/api/ai-matches/profiles/900001/analyze'
        self.assertEqual((await self.request('POST',path,headers=owner[:-1]))[0],403)
        self.assertEqual((await self.request('POST',path,headers=owner))[0],202)
        await asyncio.to_thread(self.manager.future.result,5)
        self.assertEqual((await self.request('GET','/api/ai-matches/profiles/900001',headers=owner))[1]['status'],'completed')
        self.assertEqual((await self.request('GET','/api/ai-matches/profiles/900002',headers=owner))[0],403)
        self.assertEqual((await self.request('POST','/api/ai-matches/profiles/900002/analyze',headers=owner))[0],403)

    async def test_unknown_accounts_cross_origin_and_reenabled_passwords_fail_closed(self):
        self.assertEqual((await self.request('POST','/api/evidence-session',{'account':'not-a-demo-account'},[(b'origin',b'https://test')]))[0],403)
        self.assertEqual((await self.request('POST','/api/evidence-session',{'account':'employer-001'},[(b'origin',b'https://evil.invalid')]))[0],403)
        owner=await self.login('talent-ai-001','')
        with patch.dict('os.environ',TALENTMATCH_PASSWORD_FREE_DEMO='false'):
            self.assertEqual((await self.request('GET','/api/evidence-session',headers=owner))[0],403)
            self.assertEqual((await self.request('POST','/api/evidence-session',{'account':'talent-ai-001'},[(b'origin',b'https://test')]))[0],403)
        with patch.dict('os.environ',TALENTMATCH_PASSWORD_FREE_DEMO='typo'):
            self.assertEqual((await self.request('GET','/api/evidence-session/config'))[0],503)
