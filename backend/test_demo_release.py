"""One-time deployment preparation uses only disposable synthetic SQLite files."""
import json
from pathlib import Path
import sqlite3
import unittest
from contextlib import closing
from . import database, demo_release, test_swipes
from .seed_jobs import initialize_jobs
from .jobs import read_jobs


class DemoReleaseTests(unittest.TestCase):
    setUp=test_swipes.SwipeApiTests.setUp

    def prepare(self):
        initialize_jobs()
        with database.connect() as c:
            c.execute("INSERT INTO swipe_decisions VALUES(402,1,'talent','like')")
            c.execute("INSERT INTO swipe_decisions VALUES(406,2,'talent','pass')")
            c.execute("INSERT INTO swipe_decisions VALUES(402,1,'employer','like')")
            c.execute("INSERT INTO profile_materials(candidate_id,category,title,description,skill_id,filename,content_type,content) VALUES(402,'project','Fabricated fixture','Synthetic only',1,'test.pdf','application/pdf',?)",(b'%PDF synthetic fixture only',))
        return Path(self.directory.name)/'before.sqlite3'

    def test_atomic_reset_adds_exactly_fifty_and_preserves_uploads_employers_existing_jobs(self):
        backup=self.prepare()
        with database.connect() as c:
            oldjobs=[tuple(r) for r in c.execute('SELECT * FROM job_openings')]
            existingcounts={t:c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('companies','candidates','skills','profile_materials')}
            summary=demo_release.apply(c,backup_path=backup)
            self.assertEqual(summary['new_jobs'],50)
            self.assertEqual(c.execute("SELECT sum(json_array_length(skills)) FROM candidates").fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM profile_materials WHERE skill_id IS NOT NULL').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM swipe_decisions WHERE actor='talent'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM swipe_decisions WHERE actor='employer'").fetchone()[0],1)
            for t,n in existingcounts.items():self.assertEqual(c.execute('SELECT count(*) FROM '+t).fetchone()[0],n)
            self.assertEqual(c.execute('SELECT content FROM profile_materials').fetchone()[0],b'%PDF synthetic fixture only')
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM job_openings WHERE id<910001')],oldjobs)
            jobs=read_jobs(c);self.assertEqual(len(jobs),62)
            self.assertEqual(len({j.id for j in jobs if j.id>=910001}),50)
            self.assertEqual(len({j.industry for j in jobs}),7)
        with closing(sqlite3.connect(backup)) as c:
            self.assertGreater(c.execute('SELECT sum(json_array_length(skills)) FROM candidates').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM swipe_decisions').fetchone()[0],3)
            self.assertEqual(c.execute('SELECT count(*) FROM job_openings').fetchone()[0],12)
        self.assertEqual(backup.stat().st_mode & 0o777,0o600)

    def test_preview_is_read_only_and_repeat_run_does_not_erase_new_interactions(self):
        backup=self.prepare()
        with database.connect() as c:
            before='\n'.join(c.iterdump());self.assertEqual(demo_release.preview(c)['new_jobs'],50);self.assertEqual('\n'.join(c.iterdump()),before)
            demo_release.apply(c,backup_path=backup)
            c.execute("INSERT INTO swipe_decisions VALUES(402,1,'talent','like')")
            c.execute("UPDATE candidates SET skills='[{\"skill_id\":1,\"evidence_tier\":\"self_declared\"}]' WHERE id=402")
        with database.connect() as c:
            self.assertTrue(demo_release.apply(c,backup_path=backup)['already_applied'])
            self.assertEqual(c.execute("SELECT count(*) FROM swipe_decisions WHERE actor='talent'").fetchone()[0],1)
            self.assertGreater(c.execute('SELECT json_array_length(skills) FROM candidates WHERE id=402').fetchone()[0],0)

    def test_collision_and_existing_backup_fail_without_changing_data(self):
        backup=self.prepare()
        with database.connect() as c:
            c.execute("INSERT INTO job_openings SELECT 910001,company_id,title,industry,description,must_have_skills,nice_to_have_skills,active FROM job_openings LIMIT 1")
        with database.connect() as c:
            before='\n'.join(c.iterdump())
            with self.assertRaisesRegex(ValueError,'occupied'):demo_release.apply(c,backup_path=backup)
            self.assertEqual('\n'.join(c.iterdump()),before)
            c.execute('DELETE FROM job_openings WHERE id=910001')
        backup.write_text('Preserve existing backup')
        with database.connect() as c:
            before='\n'.join(c.iterdump())
            with self.assertRaises(FileExistsError):demo_release.apply(c,backup_path=backup)
            self.assertEqual('\n'.join(c.iterdump()),before)
        self.assertEqual(backup.read_text(),'Preserve existing backup')

    def test_active_job_budget_stops_preparation_before_data_changes(self):
        backup=self.prepare()
        with database.connect() as c:
            for i in range(200000,200067):
                c.execute('INSERT INTO job_openings SELECT ?,company_id,title,industry,description,must_have_skills,nice_to_have_skills,active FROM job_openings LIMIT 1',(i,))
        with database.connect() as c:
            before='\n'.join(c.iterdump())
            with self.assertRaisesRegex(ValueError,'128-active-job'):demo_release.apply(c,backup_path=backup)
            self.assertEqual('\n'.join(c.iterdump()),before)
            self.assertFalse(backup.exists())
