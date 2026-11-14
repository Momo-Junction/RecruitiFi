import json
from unittest.mock import patch
from . import test_evidence_api as fixtures
from .evidence import sessions


class SessionTests(fixtures.EvidenceAPITests):
    async def test_configured_https_route_origin_handles_edge_termination_without_wildcard_trust(self):
        from starlette.requests import Request
        from fastapi import HTTPException
        def request(host,origin):
            return Request({'type':'http','scheme':'http','server':('backend',8080),'path':'/',
                'method':'POST','query_string':b'','headers':[(b'host',host.encode()),(b'origin',origin.encode())]})
        with patch.dict('os.environ',TALENTMATCH_PUBLIC_ORIGIN='https://demo.example.invalid'):
            sessions.origin(request('demo.example.invalid','https://demo.example.invalid'))
            for host,origin in [('demo.example.invalid','https://evil.invalid'),('evil.invalid','https://demo.example.invalid'),('demo.example.invalid','http://demo.example.invalid')]:
                with self.assertRaises(HTTPException):sessions.origin(request(host,origin))
    async def test_private_application_login_capability_fails_closed(self):
        with patch.dict('os.environ', TALENTMATCH_VERIFIED_DEMO_LOGIN='1'):
            status,data=await self.request('GET','/api/evidence-session/config',token=None)
            self.assertEqual((status,data),(200,{'verified_login_required':True}))
            with patch.dict('os.environ',TALENTMATCH_AI_SESSION_SECRET=''):
                self.assertEqual((await self.request('GET','/api/evidence-session/config',token=None))[0],503)
        with patch.dict('os.environ', TALENTMATCH_VERIFIED_DEMO_LOGIN='0'):
            self.assertEqual((await self.request('GET','/api/evidence-session/config',token=None))[1],{'verified_login_required':False})
    async def request(self, *args, **kwargs):
        app = self.app
        async def secure(scope, receive, send):
            await app({**scope, 'scheme':'https', 'server':('test',443)}, receive, send)
        self.app = secure
        try:
            return await super().request(*args, **kwargs)
        finally:
            self.app = app
    def setUp(self):
        super().setUp()
        sessions._attempts.clear()
        self.app.include_router(sessions.router)
        config = patch.dict('os.environ', {
            'TALENTMATCH_AI_SESSION_SECRET': 'synthetic-signing-secret-for-tests-only-1234',
            'TALENTMATCH_AI_DEMO_ACCOUNTS': json.dumps({'talent-001': 'synthetic-password-one', 'talent-002': 'synthetic-password-two'})})
        config.start(); self.addCleanup(config.stop)

    async def login(self):
        status, data = await self.request('POST','/api/evidence-session',body={'account':'talent-001','password':'synthetic-password-one'},token=None,headers=[(b'origin',b'http://test')])
        self.assertEqual(status,403)  # Non-loopback HTTP is deliberately refused.
        # Requests below use HTTPS to exercise Secure cookies.
        return data

    async def test_verified_cookie_scope_csrf_and_tampering(self):
        from starlette.requests import Request
        from fastapi import Response, HTTPException
        def request(method='GET', cookie=None, csrf=None):
            headers=[(b'host',b'localhost'),(b'origin',b'https://localhost')]
            if cookie: headers.append((b'cookie',cookie.encode()))
            if csrf: headers.append((b'x-recruitifi-csrf',csrf.encode()))
            return Request({'type':'http','scheme':'https','server':('localhost',443),'path':'/','headers':headers,'method':method,'query_string':b''})
        key,_=sessions.settings()
        import base64,hmac,hashlib,time
        value=base64.urlsafe_b64encode(json.dumps({'account':'talent-001','expires':time.time()+60,'csrf':'synthetic-csrf'}).encode()).decode()
        cookie=sessions.COOKIE+'='+value+'.'+hmac.new(key,value.encode(),hashlib.sha256).hexdigest()
        self.assertEqual(sessions.session(request(cookie=cookie))[1]['candidate_id'],402)
        with self.assertRaises(HTTPException): sessions.session(request('POST',cookie),write=True)
        sessions.session(request('POST',cookie,'synthetic-csrf'),write=True)
        with self.assertRaises(HTTPException): sessions.session(request(cookie=cookie+'bad'))
        status,_=await self.start(candidate=406,material=706,token=None,headers=[(b'cookie',cookie.encode()),(b'origin',b'http://test'),(b'x-recruitifi-csrf',b'synthetic-csrf')])
        self.assertEqual(status,403)

    async def test_invalid_credentials_and_login_origin(self):
        for headers in ([],[(b'origin',b'https://evil.invalid')]):
            self.assertEqual((await self.request('POST','/api/evidence-session',body={'account':'talent-001','password':'wrong'},token=None,headers=headers))[0],403)

    async def test_login_cookie_and_authorized_analysis(self):
        self.assertEqual((await self.request('POST','/api/evidence-session',body={'account':'talent-002','password':'synthetic-password-one'},token=None,headers=[(b'origin',b'https://test')]))[0],403)
        status,data=await self.request('POST','/api/evidence-session',body={'account':'talent-001','password':'synthetic-password-one'},token=None,headers=[(b'origin',b'https://test')])
        self.assertEqual(status,200)
        cookie=self.last_headers[b'set-cookie'].decode()
        self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=strict',cookie);self.assertIn('Secure',cookie)
        headers=[(b'cookie',cookie.split(';')[0].encode()),(b'origin',b'https://test'),(b'x-recruitifi-csrf',data['csrf'].encode())]
        status,accepted=await self.start(token=None,headers=headers)
        self.assertEqual(status,202)
        await self.finished(accepted['job_id'])
        self.assertEqual((await self.start(candidate=406,material=706,token=None,headers=headers))[0],403)
