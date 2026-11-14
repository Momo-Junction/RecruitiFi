"""Exercise additive jobs, shared discovery and the unchanged engine on disposable data."""
import json
import unittest
from unittest.mock import patch

from . import test_demo_accounts
from .database import connect
from .jobs import INDUSTRIES, read_jobs
from .main import app
from .matching_engine import calculate_match
from .models import MatchBreakdown
from .profile_materials import candidate_profile
from .seed_jobs import EXTRA_SKILLS, JOBS, initialize_jobs


class JobTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_demo_accounts.DemoAccountTests.setUp
    request = test_demo_accounts.DemoAccountTests.request

    def snapshot(self):
        with connect() as connection:
            tables = ['candidates', 'companies', 'skills', 'profile_materials', 'swipe_decisions', 'notifications', 'match_audit']
            return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in tables}

    async def test_migration_retains_populated_event_and_uploaded_documents(self):
        for actor in ['talent', 'employer']:
            await self.request('PUT', '/api/swipes', {**self.vote, 'actor': actor})
        await self.request('POST', '/api/candidates/402/documents?category=cv&title=Synthetic&filename=test.pdf', raw=b'%PDF-1.4\nSynthetic only\n%%EOF')
        with connect() as connection:
            connection.execute('DROP TABLE job_openings')  # Simulate the pre-feature schema in this isolated fixture.
        before = self.snapshot()
        self.assertEqual(initialize_jobs(), 12)
        after = self.snapshot()
        for table in before:
            if table == 'skills':
                self.assertEqual(after[table][:len(before[table])], before[table])
                self.assertEqual(len(after[table]), len(before[table]) + 6)
            else:
                self.assertEqual(after[table], before[table], table)
        self.assertEqual(initialize_jobs(), 0)
        self.assertEqual(self.snapshot(), after)

    async def test_explicit_initializer_is_deterministic_and_startup_never_seeds(self):
        async with app.router.lifespan_context(app):
            pass
        self.assertEqual(await self.request('GET', '/api/jobs'), (200, []))
        initialize_jobs()
        _, jobs = await self.request('GET', '/api/jobs')
        self.assertEqual([j['id'] for j in jobs], [j[0] for j in JOBS])
        self.assertEqual({j['industry'] for j in jobs}, {c['id'] for c in INDUSTRIES})
        with connect() as connection:
            catalog = {r['name']: r['id'] for r in connection.execute('SELECT id, name FROM skills')}
        self.assertTrue(all(name in catalog for name, _ in EXTRA_SKILLS))
        for job, seed in zip(jobs, JOBS):
            self.assertEqual(job['company_id'], seed[1])
            self.assertEqual(job['must_have_skills'], [{'skill_id': catalog[name], 'weight': weight} for name, weight in seed[5].items()])
            self.assertEqual(sum(s['weight'] for s in job['must_have_skills']), 70)
            self.assertEqual(sum(s['weight'] for s in job['nice_to_have_skills']), 20)
        with connect() as connection:
            connection.execute("UPDATE job_openings SET title='Operator edited', active=0, must_have_skills=? WHERE id=1001", (json.dumps([{'skill_id': 1, 'weight': 70}]),))
            edited = tuple(connection.execute('SELECT * FROM job_openings WHERE id=1001').fetchone())
        async with app.router.lifespan_context(app):
            pass
        self.assertEqual(initialize_jobs(), 0)
        with connect() as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM job_openings WHERE id=1001').fetchone()), edited)

    async def test_all_categories_or_filtering_clear_and_unknown_categories(self):
        initialize_jobs()
        status, categories = await self.request('GET', '/api/jobs/industries')
        self.assertEqual(status, 200)
        self.assertEqual([c['label'] for c in categories], ['IT', 'Business (Services)', 'Logistics', 'Health Sector', 'Restaurant', 'Cleaning', 'Engineering'])
        all_jobs = (await self.request('GET', '/api/jobs'))[1]
        for category in categories:
            jobs = (await self.request('GET', '/api/jobs?industry=' + category['id']))[1]
            self.assertTrue(jobs)
            self.assertTrue(all(j['industry'] == category['id'] for j in jobs))
        both = (await self.request('GET', '/api/jobs?industry=it&industry=engineering'))[1]
        self.assertEqual({j['id'] for j in both}, {j['id'] for j in all_jobs if j['industry'] in ['it', 'engineering']})
        self.assertEqual((await self.request('GET', '/api/jobs'))[1], all_jobs)
        self.assertEqual((await self.request('GET', '/api/jobs?industry=healthcare'))[0], 422)
        self.assertEqual(await self.request('GET', '/api/jobs?company_id=1&industry=restaurant'), (200, []))

    async def test_company_job_ownership_and_demo_identity_guards(self):
        initialize_jobs()
        for identity in range(1, 6):
            status, jobs = await self.request('GET', f'/api/companies/{identity}/jobs', account=f'employer-{identity:03}')
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(jobs), 2)
            self.assertTrue(all(job['company_id'] == identity for job in jobs))
        self.assertEqual((await self.request('GET', '/api/companies/2/jobs', account='employer-001'))[0], 403)
        self.assertEqual((await self.request('GET', '/api/jobs/2001/matches', account='employer-001'))[0], 403)
        self.assertEqual((await self.request('GET', '/api/jobs/1001/matches', account='talent-001'))[0], 403)
        self.assertEqual((await self.request('GET', '/api/candidates/406/job-matches', account='talent-001'))[0], 403)
        self.assertEqual(len((await self.request('GET', '/api/companies'))[1]), 8)

    async def test_job_switch_changes_real_rankings_and_reuses_existing_engine(self):
        initialize_jobs()
        with patch('backend.jobs.calculate_match', wraps=calculate_match) as engine:
            software = (await self.request('GET', '/api/jobs/1001/matches', account='employer-001'))[1]
            hardware = (await self.request('GET', '/api/jobs/1002/matches', account='employer-001'))[1]
        self.assertEqual(engine.call_count, 30)
        self.assertEqual(software[0]['candidate_id'], 402)
        self.assertEqual(hardware[0]['candidate_id'], 438)
        self.assertNotEqual([(m['candidate_id'], m['total_score']) for m in software], [(m['candidate_id'], m['total_score']) for m in hardware])
        with connect() as connection:
            job = read_jobs(connection, job_id=1001)[0]
            names = {r['id']: r['name'] for r in connection.execute('SELECT id, name FROM skills')}
            for actual in software:
                profile = candidate_profile(connection, actual['candidate_id'])['candidate']
                expected = MatchBreakdown.model_validate(calculate_match(profile, job, skill_names=names)).model_dump()
                self.assertEqual({key: actual[key] for key in expected}, expected)
                self.assertNotIn('full_name', actual)
                self.assertNotIn('email', actual)
                self.assertNotIn('materials', actual)
        self.assertEqual(software, sorted(software, key=lambda m: (not m['dealbreakers_passed'], -m['total_score'], m['candidate_id'])))

    async def test_talent_scores_match_employer_scores_without_changing_identity(self):
        initialize_jobs()
        talent = (await self.request('GET', '/api/candidates/402/job-matches', account='talent-001'))[1]
        self.assertEqual(len(talent), 12)
        for mine in talent:
            ranked = (await self.request('GET', f"/api/jobs/{mine['job_id']}/matches"))[1]
            theirs = next(m for m in ranked if m['candidate_id'] == 402)
            self.assertEqual(mine, {key: theirs[key] for key in mine})
        profile = (await self.request('GET', '/api/candidates/402/profile', account='talent-001'))[1]
        self.assertEqual(profile['candidate']['id'], 402)

    async def test_weights_evidence_and_domain_skills_are_not_fabricated(self):
        before = self.snapshot()['candidates']
        initialize_jobs()
        initial = (await self.request('GET', '/api/candidates/402/job-matches', account='talent-001'))[1]
        software = next(m for m in initial if m['job_id'] == 1001)
        self.assertEqual(software['must_have_points'], 49)  # 40*0.7 + 30*0.7
        with connect() as connection:
            skill_id = connection.execute("SELECT id FROM skills WHERE name='Quantum circuit programming with Qiskit'").fetchone()[0]
        await self.request('POST', '/api/candidates/402/links', {'category': 'certificate', 'title': 'Synthetic certificate', 'url': 'https://example.com/synthetic', 'skill_id': skill_id}, account='talent-001')
        updated = (await self.request('GET', '/api/candidates/402/job-matches', account='talent-001'))[1]
        self.assertEqual(next(m for m in updated if m['job_id'] == 1001)['must_have_points'], 58)
        cleaning = (await self.request('GET', '/api/jobs/3002/matches'))[1]
        self.assertTrue(all(m['must_have_points'] == 0 for m in cleaning))
        self.assertEqual(self.snapshot()['candidates'], before)

    async def test_language_visa_threshold_and_company_matching_stay_unchanged(self):
        baseline = (await self.request('GET', '/api/companies/1/matches'))[1]
        initialize_jobs()
        self.assertEqual((await self.request('GET', '/api/companies/1/matches'))[1], baseline)
        health = (await self.request('GET', '/api/jobs/3001/matches'))[1]
        sponsored = next(m for m in health if m['candidate_id'] == 406)
        self.assertFalse(sponsored['dealbreakers_passed'])
        self.assertTrue(any('visa sponsorship' in reason for reason in sponsored['dealbreaker_reasons']))
        self.assertTrue(any('Finnish' in reason for reason in sponsored['dealbreaker_reasons']))
        self.assertTrue(all(m['min_match_threshold'] == 75 for m in health))
        self.assertEqual((await self.request('GET', '/api/jobs/1001'))[1]['min_match_threshold'], 75)
        with connect() as connection:
            connection.execute("UPDATE companies SET working_language='Swedish', min_match_threshold=80 WHERE id=1")
        job = (await self.request('GET', '/api/jobs/1001'))[1]
        self.assertEqual((job['working_language'], job['min_match_threshold']), ('Swedish', 80))

    async def test_job_views_never_change_company_swipes_notifications_or_interest(self):
        initialize_jobs()
        for actor in ['talent', 'employer']:
            await self.request('PUT', '/api/swipes', {**self.vote, 'actor': actor})
        before = self.snapshot()
        for identity in [1001, 1002, 1003]:
            await self.request('GET', f'/api/jobs/{identity}/matches', account='employer-001')
        await self.request('GET', '/api/jobs?industry=engineering', account='talent-001')
        await self.request('GET', '/api/candidates/402/job-matches', account='talent-001')
        self.assertEqual(before, self.snapshot())
        inbox = (await self.request('GET', '/api/notifications/employer/1', account='employer-001'))[1]
        self.assertEqual(inbox['unread_count'], 1)
        self.assertEqual(inbox['entries'][0]['kind'], 'match')

    async def test_inactive_jobs_validation_and_missing_records(self):
        initialize_jobs()
        with connect() as connection:
            connection.execute('UPDATE job_openings SET active=0 WHERE id=1001')
        self.assertNotIn(1001, [j['id'] for j in (await self.request('GET', '/api/jobs'))[1]])
        self.assertIn(1001, [j['id'] for j in (await self.request('GET', '/api/companies/1/jobs', account='employer-001'))[1]])
        self.assertNotIn(1001, [m['job_id'] for m in (await self.request('GET', '/api/candidates/402/job-matches', account='talent-001'))[1]])
        for path, status in [('/api/jobs/0', 422), ('/api/jobs/99999', 404), ('/api/jobs/99999/matches', 404), ('/api/jobs?company_id=-1', 422), ('/api/jobs?company_id=99999', 404)]:
            self.assertEqual((await self.request('GET', path))[0], status)

    async def test_missing_base_records_and_reserved_id_collision_never_overwrite(self):
        with connect() as connection:
            connection.execute('DELETE FROM companies WHERE id=1')
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'Missing required demo company'):
            initialize_jobs()
        self.assertEqual(before, self.snapshot())

    async def test_reserved_id_collision_rolls_back_new_data(self):
        initialize_jobs()
        with connect() as connection:
            connection.execute('UPDATE job_openings SET company_id=2 WHERE id=1001')
            connection.execute('DELETE FROM job_openings WHERE id=5003')
        with self.assertRaisesRegex(RuntimeError, 'refusing to overwrite'):
            initialize_jobs()
        self.assertEqual(len((await self.request('GET', '/api/jobs'))[1]), 11)
