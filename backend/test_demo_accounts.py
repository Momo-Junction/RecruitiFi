"""Demo isolation guards use disposable seed data, never the deployed database."""
import json
import unittest
from urllib.parse import urlsplit

from .database import connect
from .demo_accounts import EMPLOYER_IDS, TALENT_IDS
from .main import app
from . import test_swipes


class DemoAccountTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_swipes.SwipeApiTests.setUp

    async def request(self, method, path='/api/demo/accounts', value=None, account=None, raw=None, extra_headers=()):
        messages = []
        payload = raw if raw is not None else json.dumps(value).encode() if value is not None else b''
        headers = [(b'content-type', b'application/json'), *extra_headers]
        if account is not None:
            headers.append((b'x-recruitifi-demo-account', account.encode()))
        async def receive():
            return {'type': 'http.request', 'body': payload, 'more_body': False}
        async def send(message):
            messages.append(message)
        url = urlsplit(path)
        await app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                   'method': method, 'scheme': 'http', 'path': url.path, 'raw_path': url.path.encode(),
                   'query_string': url.query.encode(), 'root_path': '', 'headers': headers,
                   'client': ('127.0.0.1', 12345), 'server': ('test', 80)}, receive, send)
        body = b''.join(message.get('body', b'') for message in messages)
        try:
            result = json.loads(body)
        except ValueError:
            result = body
        return messages[0]['status'], result

    async def test_exact_deterministic_accounts_reference_existing_profiles(self):
        status, catalog = await self.request('GET')
        self.assertEqual(status, 200)
        talents = [a for a in catalog['accounts'] if a['role'] == 'talent']
        employers = [a for a in catalog['accounts'] if a['role'] == 'employer']
        admins = [a for a in catalog['accounts'] if a['role'] == 'organizer']
        self.assertEqual([a['candidate_id'] for a in talents], list(TALENT_IDS))
        self.assertEqual([a['company_id'] for a in employers], list(EMPLOYER_IDS))
        self.assertEqual(len({a['candidate_id'] for a in talents}), 15)
        self.assertEqual(len({a['company_id'] for a in employers}), 5)
        self.assertEqual([a['demo_account_id'] for a in talents], [f'talent-{i:03}' for i in range(1, 16)])
        self.assertEqual([a['demo_account_id'] for a in employers], [f'employer-{i:03}' for i in range(1, 6)])
        self.assertEqual(len(admins), 1)
        self.assertTrue(all(a['available'] for a in catalog['accounts']))
        self.assertEqual((catalog['candidate_count'], catalog['company_count']), (15, 8))
        with connect() as connection:
            for a in talents:
                self.assertEqual(connection.execute('SELECT full_name FROM candidates WHERE id=?', (a['candidate_id'],)).fetchone()[0], a['display_name'])
            for a in employers:
                self.assertEqual(connection.execute('SELECT name FROM companies WHERE id=?', (a['company_id'],)).fetchone()[0], a['display_name'])

    async def test_directory_exposes_only_own_profile_and_all_discovery_companies(self):
        for index, identity in enumerate(TALENT_IDS, 1):
            account = f'talent-{index:03}'
            status, candidates = await self.request('GET', '/api/candidates', account=account)
            self.assertEqual((status, [c['id'] for c in candidates]), (200, [identity]))
            status, profile = await self.request('GET', f'/api/candidates/{identity}/profile', account=account)
            self.assertEqual((status, profile['candidate']['id']), (200, identity))
        for role in ['employer-001', 'organizer-001']:
            self.assertEqual(await self.request('GET', '/api/candidates', account=role), (200, []))
        self.assertEqual(len((await self.request('GET', '/api/companies', account='talent-001'))[1]), 8)
        matches = (await self.request('GET', '/api/companies/1/matches', account='employer-001'))[1]
        self.assertEqual(len(matches), 15)
        self.assertEqual(matches, (await self.request('GET', '/api/companies/1/matches'))[1])
        self.assertTrue(all('full_name' not in m and 'email' not in m and 'materials' not in m for m in matches))

    async def test_talent_rejects_other_profile_reads_and_writes_before_mutation(self):
        with connect() as connection:
            before = [tuple(r) for r in connection.execute('SELECT * FROM candidates ORDER BY id')]
        for method, path, body in [('GET', '/profile', None), ('PUT', '/skills', []),
                                   ('POST', '/links', {'category': 'website', 'title': 'Synthetic', 'url': 'https://example.com'}),
                                   ('POST', '/documents?category=cv&title=Synthetic&filename=test.pdf', None),
                                   ('GET', '/documents/1', None), ('DELETE', '/materials/1', None)]:
            self.assertEqual((await self.request(method, '/api/candidates/406' + path, body, account='talent-001'))[0], 403)
        self.assertEqual((await self.request('PUT', '/api/candidates/402/skills', [], account='talent-001'))[0], 200)
        with connect() as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM candidates WHERE id=406').fetchone()), next(r for r in before if r[0] == 406))
            self.assertEqual(connection.execute('SELECT count(*) FROM profile_materials').fetchone()[0], 0)

    async def test_employer_cannot_edit_other_company_or_candidate(self):
        companies = (await self.request('GET', '/api/companies', account='employer-001'))[1]
        original = companies[1]
        payload = {key: companies[0][key] for key in ['working_language', 'relocation_support', 'min_match_threshold', 'must_have_skills', 'nice_to_have_skills']}
        self.assertEqual((await self.request('PUT', '/api/companies/2/role', payload, account='employer-001'))[0], 403)
        self.assertEqual((await self.request('PUT', '/api/companies/1/role', payload, account='employer-001'))[0], 200)
        self.assertEqual((await self.request('GET', '/api/companies'))[1][1], original)
        self.assertEqual((await self.request('PUT', '/api/candidates/402/skills', [], account='employer-001'))[0], 403)
        self.assertEqual((await self.request('GET', '/api/candidates/402/profile', account='employer-001'))[0], 403)

    async def test_pair_swipes_and_inboxes_stay_scoped_to_accounts(self):
        vote = self.vote
        self.assertEqual((await self.request('PUT', '/api/swipes', {**vote, 'candidate_id': 406}, 'talent-001'))[0], 403)
        self.assertEqual((await self.request('PUT', '/api/swipes', {**vote, 'actor': 'employer'}, 'talent-001'))[0], 403)
        self.assertEqual((await self.request('PUT', '/api/swipes', {**vote, 'candidate_id': '406'}, 'talent-001'))[0], 403)
        self.assertEqual((await self.request('PUT', '/api/swipes', vote, 'talent-001'))[0], 200)
        self.assertEqual((await self.request('GET', '/api/notifications/employer/1', account='employer-001'))[1]['entries'], [])
        status, matched = await self.request('PUT', '/api/swipes', {**vote, 'actor': 'employer'}, 'employer-001')
        self.assertEqual(status, 200)
        self.assertTrue(matched['mutual_match'])
        for account, role, identity in [('talent-001', 'talent', 402), ('employer-001', 'employer', 1)]:
            inbox = (await self.request('GET', f'/api/notifications/{role}/{identity}', account=account))[1]
            self.assertEqual((len(inbox['entries']), inbox['unread_count']), (1, 1))
        self.assertEqual((await self.request('GET', '/api/notifications/talent/406', account='talent-002'))[1]['entries'], [])
        self.assertEqual((await self.request('GET', '/api/notifications/employer/2', account='employer-002'))[1]['entries'], [])
        self.assertEqual((await self.request('GET', '/api/notifications/talent/402', account='talent-002'))[0], 403)
        self.assertEqual((await self.request('PUT', '/api/notifications/talent/402/1/read', account='talent-002'))[0], 403)
        self.assertEqual((await self.request('GET', '/api/swipes', account='talent-002'))[1], [])
        self.assertEqual((await self.request('GET', '/api/swipes', account='employer-002'))[1], [])
        self.assertEqual((await self.request('DELETE', '/api/swipes/talent/402/1', account='talent-002'))[0], 403)
        self.assertEqual((await self.request('DELETE', '/api/swipes/employer/402/1', account='employer-002'))[0], 403)
        self.assertEqual((await self.request('DELETE', '/api/swipes/talent/402/1', account='talent-001'))[0], 200)

    async def test_own_document_upload_and_download_preserve_existing_data(self):
        document = b'%PDF-1.4\nSynthetic account test\n%%EOF\n'
        path = '/api/candidates/402/documents?category=cv&title=Synthetic&filename=synthetic.pdf'
        status, profile = await self.request('POST', path, account='talent-001', raw=document)
        self.assertEqual(status, 200)
        material_id = profile['materials'][0]['id']
        download = f'/api/candidates/402/documents/{material_id}'
        self.assertEqual(await self.request('GET', download, account='talent-001'), (200, document))
        self.assertEqual(await self.request('GET', download), (200, document))  # Existing direct demo links have no account header.
        self.assertEqual((await self.request('GET', download, account='talent-002'))[0], 403)
        await self.request('GET')
        async with app.router.lifespan_context(app):
            pass
        self.assertEqual(await self.request('GET', download, account='talent-001'), (200, document))
        with connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM candidates').fetchone()[0], 15)
            self.assertEqual(connection.execute('SELECT count(*) FROM companies').fetchone()[0], 8)

    async def test_missing_record_has_clear_unavailable_account_without_remapping(self):
        with connect() as connection:
            connection.execute('DELETE FROM candidates WHERE id=402')
        status, catalog = await self.request('GET', account='talent-001')
        self.assertEqual(status, 200)
        first = catalog['accounts'][0]
        self.assertEqual(first['candidate_id'], 402)
        self.assertFalse(first['available'])
        self.assertIn('missing', first['error'])
        self.assertEqual((await self.request('GET', '/api/candidates', account='talent-001'))[0], 409)
        self.assertEqual(len((await self.request('GET', '/api/companies'))[1]), 8)

    async def test_unknown_and_duplicate_account_headers_are_rejected(self):
        self.assertEqual((await self.request('GET', '/api/companies', account='talent-999'))[0], 400)
        self.assertEqual((await self.request('GET', '/api/companies', account='talent-001', extra_headers=[(b'x-recruitifi-demo-account', b'talent-002')]))[0], 400)

    async def test_organizer_keeps_matching_but_cannot_write_personal_profiles(self):
        self.assertEqual(len((await self.request('GET', '/api/companies/1/matches', account='organizer-001'))[1]), 15)
        self.assertEqual((await self.request('PUT', '/api/candidates/402/skills', [], account='organizer-001'))[0], 403)
        self.assertEqual((await self.request('PUT', '/api/swipes', self.vote, 'organizer-001'))[0], 403)

    async def test_demo_header_is_allowed_in_local_development_preflight(self):
        status, _ = await self.request('OPTIONS', '/api/candidates/402/skills', extra_headers=[
            (b'origin', b'http://localhost:5173'), (b'access-control-request-method', b'PUT'),
            (b'access-control-request-headers', b'content-type,x-recruitifi-demo-account')])
        self.assertEqual(status, 200)
