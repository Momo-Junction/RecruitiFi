"""Exercise the swipe API with an isolated SQLite event and no extra test dependencies."""
import json
import io
from contextlib import redirect_stdout
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .main import app
from .seed import DEMO_NOTE, seed


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

    async def request(self, method, path='/api/swipes', value=None):
        messages = []
        payload = json.dumps(value).encode() if value is not None else b''

        async def receive():
            return {'type': 'http.request', 'body': payload, 'more_body': False}

        async def send(message):
            messages.append(message)

        await app({
            'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
            'query_string': b'', 'root_path': '', 'headers': [(b'content-type', b'application/json')],
            'client': ('127.0.0.1', 12345), 'server': ('test', 80),
        }, receive, send)
        body = b''.join(message.get('body', b'') for message in messages)
        return messages[0]['status'], json.loads(body) if body else None

    async def test_likes_persist_and_both_sides_are_independent(self):
        self.assertEqual(await self.request('GET'), (200, []))
        self.assertEqual(await self.request('PUT', value=self.vote), (200, self.vote))
        self.assertEqual(await self.request('PUT', value=self.vote), (200, self.vote))
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

    async def test_saved_profile_routes_load_and_persist_materials(self):
        _, candidates = await self.request('GET', '/api/candidates')
        for candidate in candidates:
            status, saved = await self.request('GET', f"/api/candidates/{candidate['id']}/profile")
            self.assertEqual(status, 200)
            self.assertEqual(saved['candidate']['id'], candidate['id'])
            self.assertTrue(all(item['description'] == DEMO_NOTE for item in saved['materials']))
        _, before = await self.request('GET', '/api/candidates/402/profile')
        status, saved = await self.request('POST', '/api/candidates/402/links', {
            'category': 'project', 'title': 'Portfolio', 'url': 'https://example.com/portfolio', 'skill_id': 1,
        })
        self.assertEqual(status, 200)
        self.assertTrue(saved['candidate']['has_portfolio'])
        self.assertEqual(len(saved['materials']), len(before['materials']) + 1)
        self.assertEqual(await self.request('GET', '/api/candidates/402/profile'), (200, saved))
        self.assertEqual((await self.request('GET', '/api/candidates/99999/profile'))[0], 404)

    async def test_reseeding_preserves_decisions(self):
        await self.request('PUT', value=self.vote)
        with redirect_stdout(io.StringIO()):
            seed()
        self.assertEqual(await self.request('GET'), (200, [self.vote]))

    async def test_reseeding_replaces_demo_materials_and_keeps_uploads(self):
        _, before = await self.request('GET', '/api/candidates/402/profile')
        await self.request('POST', '/api/candidates/402/links', {
            'category': 'project', 'title': 'My own project', 'url': 'https://example.com/mine', 'skill_id': 1,
        })
        with redirect_stdout(io.StringIO()):
            seed()
        _, after = await self.request('GET', '/api/candidates/402/profile')
        self.assertEqual(len(after['materials']), len(before['materials']) + 1)
        self.assertIn('My own project', [item['title'] for item in after['materials']])

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

    async def test_seeded_event_has_evidence_backed_introductions(self):
        _, companies = await self.request('GET', '/api/companies')
        eligible = set()
        for company in companies:
            status, matches = await self.request('GET', f"/api/companies/{company['id']}/matches")
            self.assertEqual(status, 200)
            self.assertEqual(len(matches), 15)
            eligible |= {company['id'] for m in matches if m['dealbreakers_passed'] and m['meets_threshold']}
        # Every booth but Kuura Software (only strong candidate needs visa sponsorship) has a suggestion.
        self.assertEqual(eligible, {company['id'] for company in companies} - {8})

    async def test_organizer_requires_evidence_not_swipe_interactions(self):
        # Seeded proof makes persona 402 eligible for company 1 without any swipes.
        _, matches = await self.request('GET', '/api/companies/1/matches')
        match = next(m for m in matches if m['candidate_id'] == 402)
        self.assertEqual(match['total_score'], 85)
        self.assertTrue(match['dealbreakers_passed'] and match['meets_threshold'])
        self.assertEqual((await self.request('GET'))[1], [])  # no swipes/likes needed
        # Removing the proof drops the same claims to listed skills and below the threshold.
        _, profile = await self.request('GET', '/api/candidates/402/profile')
        for item in profile['materials']:
            self.assertEqual((await self.request('DELETE', f"/api/candidates/402/materials/{item['id']}"))[0], 200)
        _, matches = await self.request('GET', '/api/companies/1/matches')
        match = next(m for m in matches if m['candidate_id'] == 402)
        self.assertFalse(match['meets_threshold'])

    async def test_meeting_request_reveals_identity_only_on_mutual_interest(self):
        path = '/api/companies/1/matches/Talent #402/accept'  # ASGI paths arrive decoded
        status, pending = await self.request('POST', path)
        self.assertEqual(status, 200)
        self.assertFalse(pending['revealed'])
        self.assertIsNone(pending['full_name'])
        self.assertIsNone(pending['email'])
        self.assertTrue(pending['conversation_starter'])
        # The request is recorded as the employer's interest.
        self.assertEqual((await self.request('GET'))[1], [{**self.vote, 'actor': 'employer'}])
        # Once the candidate also chooses the company, the contact is shared.
        await self.request('PUT', value=self.vote)
        _, mutual = await self.request('POST', path)
        self.assertTrue(mutual['revealed'])
        self.assertEqual(mutual['email'], 'talent402@example.com')
        # A candidate who passed is never revealed.
        await self.request('PUT', value={**self.vote, 'decision': 'pass'})
        self.assertFalse((await self.request('POST', path))[1]['revealed'])

    async def test_invalid_votes_do_not_write(self):
        for field, value, expected in [('actor', 'unknown', 422), ('decision', 'yes', 422), ('candidate_id', -1, 422), ('candidate_id', 99999, 404), ('company_id', 99999, 404)]:
            with self.subTest(field=field, value=value):
                self.assertEqual((await self.request('PUT', value={**self.vote, field: value}))[0], expected)
        self.assertEqual((await self.request('GET'))[1], [])


if __name__ == '__main__':
    unittest.main()
