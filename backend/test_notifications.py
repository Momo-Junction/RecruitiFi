"""Notification state-machine/API checks against disposable synthetic event databases."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from . import test_swipes
from .database import connect, SCHEMA_PATH
from .main import app, lifespan, save_swipe
from .models import SwipeDecision
from .notifications import initialize_notifications


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_swipes.SwipeApiTests.setUp
    request = test_swipes.SwipeApiTests.request

    async def decide(self, actor, decision='like', candidate=402, company=1):
        status, value = await self.request('PUT', value=dict(candidate_id=candidate, company_id=company, actor=actor, decision=decision))
        self.assertEqual(status, 200)
        return value

    async def feed(self, actor='talent', identity=402):
        status, feed = await self.request('GET', f'/api/notifications/{actor}/{identity}')
        self.assertEqual(status, 200)
        self.assertEqual(feed['unread_count'], sum(n['read_at'] is None for n in feed['entries']))
        return feed

    async def test_talent_interest_has_badge_data_but_never_employer_notification(self):
        result = await self.decide('talent')
        self.assertFalse(result['mutual_match'])
        self.assertEqual((await self.feed('employer', 1))['entries'], [])
        self.assertEqual((await self.feed())['entries'], [])
        _, swipes = await self.request('GET')
        self.assertIn(dict(candidate_id=402, company_id=1, actor='talent', decision='like'), swipes)
        self.assertEqual((await self.feed('employer', 2))['entries'], [])
        await self.decide('talent', 'pass')
        _, swipes = await self.request('GET')
        self.assertFalse(any(s['actor']=='talent' and s['decision']=='like' for s in swipes))

    async def test_employer_interest_is_scoped_to_its_talent(self):
        self.assertFalse((await self.decide('employer'))['mutual_match'])
        feed = await self.feed()
        self.assertEqual([n['kind'] for n in feed['entries']], ['interest'])
        self.assertEqual(feed['entries'][0]['message'], 'Kide Quantum Labs is interested in you!')
        self.assertEqual((await self.feed('talent', 406))['entries'], [])
        self.assertEqual((await self.feed('employer', 1))['entries'], [])
        await self.decide('employer', 'pass')
        self.assertEqual((await self.feed())['entries'], [])

    async def assert_mutual(self, first, second):
        await self.decide(first)
        self.assertTrue((await self.decide(second))['mutual_match'])
        for actor, identity in [('talent', 402), ('employer', 1)]:
            feed = await self.feed(actor, identity)
            self.assertEqual([n['kind'] for n in feed['entries']], ['match'])
            self.assertTrue(feed['entries'][0]['message'].startswith("It's a Match!"))
            self.assertEqual(feed['unread_count'], 1)

    async def test_talent_then_employer_creates_two_match_notifications(self):
        await self.assert_mutual('talent', 'employer')

    async def test_employer_then_talent_supersedes_interest(self):
        await self.assert_mutual('employer', 'talent')

    async def test_repeated_likes_preserve_notification_and_read_state(self):
        await self.decide('employer')
        before = await self.feed()
        notification = before['entries'][0]['id']
        status, read = await self.request('PUT', f'/api/notifications/talent/402/{notification}/read')
        self.assertEqual(status, 200)
        self.assertEqual(read['unread_count'], 0)
        for _ in range(3):
            await self.decide('employer')
        after = await self.feed()
        self.assertEqual(after, read)
        self.assertEqual(before['entries'][0]['created_at'], after['entries'][0]['created_at'])

    async def test_repeated_mutual_likes_are_idempotent(self):
        await self.assert_mutual('talent', 'employer')
        before = await self.feed()
        for _ in range(3):
            self.assertTrue((await self.decide('talent'))['mutual_match'])
            self.assertTrue((await self.decide('employer'))['mutual_match'])
        self.assertEqual(await self.feed(), before)
        self.assertEqual(len((await self.feed('employer', 1))['entries']), 1)

    async def test_withdraw_employer_like_deactivates_both_matches(self):
        await self.assert_mutual('talent', 'employer')
        await self.request('DELETE', '/api/swipes/employer/402/1')
        self.assertEqual((await self.feed())['entries'], [])
        self.assertEqual((await self.feed('employer', 1))['entries'], [])
        self.assertTrue((await self.decide('employer'))['mutual_match'])
        self.assertEqual(len((await self.feed())['entries']), 1)

    async def test_withdraw_talent_like_restores_only_current_employer_interest(self):
        await self.assert_mutual('employer', 'talent')
        await self.decide('talent', 'pass')
        self.assertEqual([n['kind'] for n in (await self.feed())['entries']], ['interest'])
        self.assertEqual((await self.feed('employer', 1))['entries'], [])
        await self.decide('employer', 'pass')
        self.assertEqual((await self.feed())['entries'], [])

    async def test_read_scoping_and_inactive_notifications(self):
        await self.decide('employer')
        notification = (await self.feed())['entries'][0]['id']
        for actor, identity in [('talent', 406), ('employer', 1), ('employer', 2)]:
            self.assertEqual((await self.request('PUT', f'/api/notifications/{actor}/{identity}/{notification}/read'))[0], 404)
        self.assertEqual((await self.feed())['unread_count'], 1)
        await self.decide('employer', 'pass')
        self.assertEqual((await self.request('PUT', f'/api/notifications/talent/402/{notification}/read'))[0], 404)
        self.assertEqual((await self.request('GET', '/api/notifications/talent/99999'))[0], 404)
        self.assertEqual((await self.request('GET', '/api/notifications/organizer/402'))[0], 422)

    async def test_existing_likes_backfill_repeatably_and_survive_startup(self):
        with connect() as db:
            db.execute("INSERT INTO swipe_decisions VALUES (402,1,'employer','like')")
            db.execute("INSERT INTO profile_materials(candidate_id,category,title,filename,content_type,content) VALUES (402,'cv','Synthetic','test.pdf','application/pdf',?)", (b'%PDF-synthetic',))
            db.executescript(SCHEMA_PATH.read_text())
            initialize_notifications(db)
        notification = (await self.feed())['entries'][0]['id']
        await self.request('PUT', f'/api/notifications/talent/402/{notification}/read')
        before = await self.feed()
        with patch.dict('os.environ', {'TALENTMATCH_HOSTED_DEMO':'0', 'TALENTMATCH_SERVE_FRONTEND':'1'}):
            for _ in range(2):
                async with lifespan(app):
                    pass
        self.assertEqual(await self.feed(), before)
        with connect() as db:
            self.assertEqual(db.execute('SELECT content FROM profile_materials').fetchone()[0], b'%PDF-synthetic')
            self.assertEqual(db.execute('SELECT count(*) FROM candidates').fetchone()[0], 15)
            self.assertEqual(db.execute('SELECT count(*) FROM notifications').fetchone()[0], 1)

    async def test_concurrent_identical_likes_never_duplicate_active_matches(self):
        values = [SwipeDecision(candidate_id=402, company_id=1, actor=actor, decision='like') for actor in ['talent', 'employer'] * 6]
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(save_swipe, values))
        self.assertEqual([n['kind'] for n in (await self.feed())['entries']], ['match'])
        self.assertEqual([n['kind'] for n in (await self.feed('employer', 1))['entries']], ['match'])

    async def test_swipe_rolls_back_if_notification_update_fails(self):
        with patch('backend.main.reconcile_pair', side_effect=RuntimeError('Synthetic transactional failure')):
            with self.assertRaisesRegex(RuntimeError, 'Synthetic transactional failure'):
                save_swipe(SwipeDecision(candidate_id=402, company_id=1, actor='employer', decision='like'))
        self.assertEqual((await self.request('GET'))[1], [])
        self.assertEqual((await self.feed())['entries'], [])
