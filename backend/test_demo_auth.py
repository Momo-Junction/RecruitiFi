"""Shared hosted-demo access checks, with generated synthetic credentials only."""
import base64
import os
import secrets
import subprocess
import sys
import unittest
from unittest.mock import patch

from .demo_auth import DemoAuthMiddleware, hosted_password


class DemoAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(24) + 'å'
        self.environment = patch.dict(os.environ, {
            'TALENTMATCH_HOSTED_DEMO': '1', 'TALENTMATCH_DEMO_AUTH_ENABLED': 'true', 'TALENTMATCH_DEMO_PASSWORD': self.password,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.called = 0

        async def downstream(scope, receive, send):
            self.called += 1
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'protected response'})

        self.app = DemoAuthMiddleware(downstream)

    def basic(self, username='demo', password=None):
        password = self.password if password is None else password
        return b'Basic ' + base64.b64encode(f'{username}:{password}'.encode('utf-8'))

    async def request(self, path='/', method='GET', headers=()):
        messages = []

        async def receive():
            raise AssertionError('Middleware must not read an unauthorized request body.')

        async def send(message):
            messages.append(message)

        await self.app({'type': 'http', 'path': path, 'method': method, 'headers': headers}, receive, send)
        return messages

    async def test_every_hosted_surface_is_protected_before_body_processing(self):
        for path in ['/', '/assets/app.js', '/docs', '/redoc', '/openapi.json', '/api/companies',
                     '/api/candidates/402/profile', '/api/candidates/402/documents/1']:
            for method in ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']:
                with self.subTest(path=path, method=method):
                    messages = await self.request(path, method)
                    self.assertEqual(messages[0]['status'], 401)
                    self.assertIn(b'Basic realm=', dict(messages[0]['headers'])[b'www-authenticate'])
        self.assertEqual(self.called, 0)

    async def test_invalid_and_malformed_credentials_are_rejected(self):
        bad = [b'Bearer anything', b'Basic !!!', b'Basic bm9jb2xvbg==', b'Basic', b'',
               self.basic(username='someone-else'), self.basic(password=secrets.token_urlsafe(24))]
        for header in bad:
            with self.subTest(header_type=header.split(b' ', 1)[0]):
                messages = await self.request(headers=[(b'authorization', header)])
                self.assertEqual(messages[0]['status'], 401)
                self.assertEqual(dict(messages[0]['headers'])[b'cache-control'], b'no-store')
        self.assertEqual(self.called, 0)

    async def test_duplicate_authorization_is_rejected(self):
        messages = await self.request(headers=[(b'authorization', self.basic()), (b'authorization', self.basic())])
        self.assertEqual(messages[0]['status'], 401)
        self.assertEqual(self.called, 0)

    async def test_valid_credentials_pass_without_changing_response_body(self):
        for method in ['GET', 'POST', 'PUT', 'DELETE']:
            messages = await self.request('/api/companies', method, [(b'authorization', self.basic())])
            self.assertEqual(messages[0]['status'], 200)
            self.assertEqual(messages[1]['body'], b'protected response')
            self.assertEqual(dict(messages[0]['headers'])[b'cache-control'], b'no-store')

    async def test_only_exact_health_path_is_public(self):
        self.assertEqual((await self.request('/healthz'))[0]['status'], 200)
        for path, method in [('/healthz/', 'GET'), ('/healthz/private', 'GET'), ('/healthz', 'POST')]:
            self.assertEqual((await self.request(path, method))[0]['status'], 401)

    async def test_local_development_remains_unauthenticated(self):
        os.environ['TALENTMATCH_HOSTED_DEMO'] = '0'
        self.app = DemoAuthMiddleware(self.app.app)
        self.assertEqual((await self.request('/api/companies'))[0]['status'], 200)

    async def test_websocket_cannot_bypass_hosted_protection(self):
        messages = []

        async def send(message):
            messages.append(message)

        await self.app({'type': 'websocket'}, None, send)
        self.assertEqual(messages, [{'type': 'websocket.close', 'code': 1008}])
        self.assertEqual(self.called, 0)

    def test_missing_or_whitespace_password_fails_closed(self):
        for value in ['', '   ']:
            os.environ['TALENTMATCH_DEMO_PASSWORD'] = value
            with self.assertRaisesRegex(RuntimeError, 'PASSWORD is required'):
                hosted_password()

    def test_invalid_hosted_mode_fails_closed(self):
        os.environ['TALENTMATCH_HOSTED_DEMO'] = 'true'
        with self.assertRaisesRegex(RuntimeError, 'must be 0 or 1'):
            hosted_password()

    def test_direct_uvicorn_app_import_rejects_missing_password(self):
        result = subprocess.run(
            [sys.executable, '-c', 'import backend.main'],
            env={**os.environ, 'TALENTMATCH_DEMO_PASSWORD': ''},
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('TALENTMATCH_DEMO_PASSWORD is required', result.stderr)

    async def test_startup_validates_before_database_writes(self):
        from .main import app, lifespan
        os.environ['TALENTMATCH_DEMO_PASSWORD'] = ''
        with patch('backend.main.connect') as connect:
            with self.assertRaisesRegex(RuntimeError, 'PASSWORD is required'):
                async with lifespan(app):
                    pass
            connect.assert_not_called()

    async def test_explicit_false_allows_hosted_access_without_password(self):
        os.environ['TALENTMATCH_DEMO_AUTH_ENABLED'] = 'false'
        os.environ.pop('TALENTMATCH_DEMO_PASSWORD', None)
        self.app = DemoAuthMiddleware(self.app.app)
        for path in ['/', '/api/candidates', '/api/candidates/402/documents/1']:
            self.assertEqual((await self.request(path))[0]['status'], 200)

    def test_auth_defaults_to_enabled(self):
        os.environ.pop('TALENTMATCH_DEMO_AUTH_ENABLED', None)
        os.environ.pop('TALENTMATCH_DEMO_PASSWORD', None)
        with self.assertRaisesRegex(RuntimeError, 'PASSWORD is required'):
            hosted_password()

    def test_invalid_auth_flag_fails_closed(self):
        for value in ['', '0', 'no', 'typo']:
            os.environ['TALENTMATCH_DEMO_AUTH_ENABLED'] = value
            with self.assertRaisesRegex(RuntimeError, 'AUTH_ENABLED must be true or false'):
                hosted_password()
