"""Exercise the swipe API with an isolated SQLite event and no extra test dependencies."""
import json
import io
from contextlib import redirect_stdout
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .main import app
from .seed import seed


class SwipeApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = patch('backend.database.DB_PATH', Path(self.directory.name) / 'event.sqlite3')
        self.database.start()
        self.addCleanup(self.database.stop)
        with redirect_stdout(io.StringIO()):
            seed()
        self.vote = dict(candidate_id=402, company_id=1, actor='talent', decision='like')

    async def request(self, method, path='/api/swipes', value=None, headers=()):
        messages = []
        payload = json.dumps(value).encode() if value is not None else b''

        async def receive():
            return {'type': 'http.request', 'body': payload, 'more_body': False}

        async def send(message):
            messages.append(message)

        await app({
            'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
            'query_string': b'', 'root_path': '', 'headers': [(b'content-type', b'application/json'),*headers],
            'client': ('127.0.0.1', 12345), 'server': ('test', 80),
        }, receive, send)
        body = b''.join(message.get('body', b'') for message in messages)
        return messages[0]['status'], json.loads(body) if body else None

    async def test_likes_persist_and_both_sides_are_independent(self):
        self.assertEqual(await self.request('GET'), (200, []))
        self.assertEqual(await self.request('PUT', value=self.vote), (200, {**self.vote, 'mutual_match': False}))
        self.assertEqual(await self.request('PUT', value=self.vote), (200, {**self.vote, 'mutual_match': False}))
        employer = {**self.vote, 'actor': 'employer'}
        await self.request('PUT', value=employer)
        status, rows = await self.request('GET')
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['decision'] == 'like' for row in rows))
        await self.request('PUT', value={**self.vote, 'decision': 'pass'})
        _, rows = await self.request('GET')
        self.assertEqual({row['actor']: row['decision'] for row in rows}, {'talent': 'pass', 'employer': 'like'})
        self.assertEqual((await self.request('DELETE', '/api/swipes/talent/402/1'))[0], 200)
        self.assertEqual((await self.request('GET'))[1], [employer])

    async def test_shortlisted_candidate_can_submit_and_employer_can_verify(self):
        import base64,hmac,hashlib,time
        from .evidence.sessions import COOKIE
        key='synthetic-task-signing-key-for-tests-123456'
        config=patch.dict('os.environ',TALENTMATCH_AI_SYNTHETIC_DEMO='1',TALENTMATCH_AI_SYNTHETIC_CANDIDATES='402,406',TALENTMATCH_AI_DEMO_TOKEN='synthetic-task-operator-token-1234567890',TALENTMATCH_AI_SESSION_SECRET=key,TALENTMATCH_AI_DEMO_ACCOUNTS=json.dumps({'talent-001':'synthetic-password-1','employer-001':'synthetic-password-2'}))
        config.start();self.addCleanup(config.stop)
        async def task_request(method,path,value=None,role='employer'):
            alias='employer-001' if role=='employer' else 'talent-001'
            payload=base64.urlsafe_b64encode(json.dumps({'account':alias,'expires':time.time()+600,'csrf':'synthetic-csrf'}).encode()).decode()
            cookie=COOKIE+'='+payload+'.'+hmac.new(key.encode(),payload.encode(),hashlib.sha256).hexdigest()
            return await self.request(method,path,value,[(b'cookie',cookie.encode()),(b'origin',b'http://test'),(b'x-recruitifi-csrf',b'synthetic-csrf')])
        path = '/api/hiring-tasks'
        assignment = dict(candidate_id=402, company_id=1, title='Portfolio review', description='Share a project link.')
        employer = {**self.vote, 'actor': 'employer'}

        self.assertEqual((await task_request('POST', path, assignment))[0], 409)
        self.assertEqual((await self.request('PUT', value=employer))[0], 200)
        self.assertEqual((await task_request('POST', path, {**assignment, 'title': '   '}))[0], 422)
        status, task = await task_request('POST', path, assignment)
        self.assertEqual(status, 201)
        self.assertIsNone(task['submission_url'])
        self.assertEqual((await self.request('DELETE', '/api/swipes/employer/402/1'))[0], 409)
        self.assertEqual((await self.request('PUT', value={**employer, 'decision': 'pass'}))[0], 409)

        task_path = f"{path}/{task['id']}"
        submission = {'url': 'https://example.com/project'}
        self.assertEqual((await task_request('PUT', f'{task_path}/submission/406', submission,role='talent'))[0], 403)
        self.assertEqual((await task_request('PUT', f'{task_path}/submission/402', {'url': 'ftp://example.com/work'},role='talent'))[0], 422)
        status, submitted = await task_request('PUT', f'{task_path}/submission/402', submission,role='talent')
        self.assertEqual(status, 200)
        self.assertEqual(submitted['submission_url'], submission['url'])
        self.assertEqual((await task_request('PUT', f'{task_path}/verification/2', submission))[0], 403)
        self.assertEqual((await task_request('PUT', f'{task_path}/verification/1', {'url': 'https://example.com/old'}))[0], 409)
        status, verified = await task_request('PUT', f'{task_path}/verification/1', submission)
        self.assertEqual(status, 200)
        self.assertTrue(verified['verified'])
        self.assertEqual((await task_request('PUT', f'{task_path}/submission/402', submission,role='talent'))[0], 409)
        self.assertEqual(await task_request('GET', path), (200, [verified]))

    async def test_saved_profile_routes_load_and_persist_materials(self):
        _, candidates = await self.request('GET', '/api/candidates')
        for candidate in candidates:
            status, saved = await self.request('GET', f"/api/candidates/{candidate['id']}/profile")
            self.assertEqual(status, 200)
            self.assertEqual(saved['candidate']['id'], candidate['id'])
            self.assertEqual(saved['materials'], [])
        status, saved = await self.request('POST', '/api/candidates/402/links', {
            'category': 'project', 'title': 'Portfolio', 'url': 'https://example.com/portfolio', 'skill_id': 1,
        })
        self.assertEqual(status, 200)
        self.assertTrue(saved['candidate']['has_portfolio'])
        self.assertEqual(len(saved['materials']), 1)
        self.assertEqual(await self.request('GET', '/api/candidates/402/profile'), (200, saved))
        self.assertEqual((await self.request('GET', '/api/candidates/99999/profile'))[0], 404)

    async def test_reseeding_preserves_decisions(self):
        await self.request('PUT', value=self.vote)
        with redirect_stdout(io.StringIO()):
            seed()
        self.assertEqual(await self.request('GET'), (200, [self.vote]))

    async def test_undo_is_scoped_to_pair_and_side(self):
        employer = {**self.vote, 'actor': 'employer'}
        other_company = {**self.vote, 'company_id': 2}
        other_candidate = {**self.vote, 'candidate_id': 406}
        for vote in [self.vote, employer, other_company, other_candidate]:
            self.assertEqual((await self.request('PUT', value=vote))[0], 200)
        self.assertEqual((await self.request('DELETE', '/api/swipes/talent/402/1'))[0], 200)
        # Repeated undo is harmless and must preserve every other decision.
        self.assertEqual((await self.request('DELETE', '/api/swipes/talent/402/1'))[0], 200)
        _, rows = await self.request('GET')
        self.assertCountEqual(rows, [employer, other_company, other_candidate])
        self.assertEqual((await self.request('DELETE', '/api/swipes/unknown/402/1'))[0], 422)

    async def test_recommendations_respond_to_skill_evidence(self):
        _, companies = await self.request('GET', '/api/companies')
        company = companies[0]
        profile = dict(has_cv=True, has_portfolio=True, languages={company['working_language']: 'C2'}, needs_visa_sponsorship=False, skills=[])
        path = '/api/match/simulate'
        status, empty = await self.request('POST', path, {'company_id': company['id'], 'candidate': profile})
        self.assertEqual(status, 200)
        profile['skills'] = [dict(skill_id=skill['skill_id'], evidence_tier='certificate') for skill in company['must_have_skills'] + company['nice_to_have_skills']]
        _, complete = await self.request('POST', path, {'company_id': company['id'], 'candidate': profile})
        self.assertGreater(complete['total_score'], empty['total_score'])
        self.assertEqual(complete['total_score'], 100)
        self.assertTrue(complete['meets_threshold'])
        profile['languages'] = {}
        _, blocked = await self.request('POST', path, {'company_id': company['id'], 'candidate': profile})
        self.assertFalse(blocked['dealbreakers_passed'])
        self.assertTrue(blocked['dealbreaker_reasons'])
        # Swiping does not book a meeting or erase a language blocker.
        await self.request('PUT', value=self.vote)
        _, still_blocked = await self.request('POST', path, {'company_id': company['id'], 'candidate': profile})
        self.assertFalse(still_blocked['dealbreakers_passed'])

    async def test_organizer_requires_evidence_not_swipe_interactions(self):
        _, companies = await self.request('GET', '/api/companies')
        for company in companies:
            status, matches = await self.request('GET', f"/api/companies/{company['id']}/matches")
            self.assertEqual(status, 200)
            self.assertEqual(len(matches), 15)
            self.assertFalse(any(m['dealbreakers_passed'] and m['meets_threshold'] for m in matches))
        # Existing demo persona 402 has the language and skill claims for company 1.
        # Attach synthetic project proof to its three actual must-have skills.
        company = companies[0]
        for skill in company['must_have_skills']:
            status, _ = await self.request('POST', '/api/candidates/402/links', {
                'category': 'project', 'title': 'Synthetic hackathon project',
                'url': 'https://example.com/synthetic-project', 'skill_id': skill['skill_id'],
            })
            self.assertEqual(status, 200)
        _, matches = await self.request('GET', '/api/companies/1/matches')
        match = next(m for m in matches if m['candidate_id'] == 402)
        self.assertEqual(match['total_score'], 75)
        self.assertTrue(match['dealbreakers_passed'] and match['meets_threshold'])
        self.assertEqual((await self.request('GET'))[1], [])  # no swipes/likes needed

    async def test_invalid_votes_do_not_write(self):
        for field, value, expected in [('actor', 'unknown', 422), ('decision', 'yes', 422), ('candidate_id', -1, 422), ('candidate_id', 99999, 404), ('company_id', 99999, 404)]:
            with self.subTest(field=field, value=value):
                self.assertEqual((await self.request('PUT', value={**self.vote, field: value}))[0], expected)
        self.assertEqual((await self.request('GET'))[1], [])


if __name__ == '__main__':
    unittest.main()
