"""Disposable on-disk SQLite fixtures; no application DB, model or live network."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from . import database, test_github_fetcher as github_fixtures
from .evidence import github_fetcher, github_pipeline, semantic_matching as semantic, storage
from .profile_materials import delete_material


def seed(connection, schema):
    connection.executescript(schema)
    connection.executemany('INSERT INTO skills VALUES(?,?,?,?)',
        [(1, 'urn:test:python', 'Python', 'Test'), (3, 'urn:test:react', 'React', 'Test'),
         (4, 'urn:test:fastapi', 'FastAPI', 'Test'), (5, 'urn:test:docker', 'Docker', 'Test')])
    for identifier in (402, 403):
        connection.execute('INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?,?)',
            (identifier, f'SYNTHETIC-{identifier}', 'Synthetic Candidate', f'{identifier}@example.invalid',
             0, 0, '{"English":"B2"}', 0, '[{"skill_id":1,"evidence_tier":"self_declared"}]'))
    connection.execute('INSERT INTO companies VALUES(1,?,?,?,?,?,?,?,?)',
        ('Synthetic Company', 'IT', 'S1', 1, 'English', 50, '[{"skill_id":1,"weight":70}]', '[{"skill_id":5,"weight":20}]'))
    connection.execute("INSERT INTO job_openings VALUES(1001,1,'Synthetic Job','it','Synthetic','[]','[]',1)")
    connection.execute("INSERT INTO swipe_decisions VALUES(402,1,'talent','like')")
    connection.execute("INSERT INTO notifications(candidate_id,company_id,recipient,kind) VALUES(402,1,'talent','interest')")
    connection.execute("INSERT INTO match_audit(source,company_name,inputs,result) VALUES('test','Synthetic','{}','{\"total_score\":49}')")
    connection.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(701,402,'project','Synthetic Python project','Built Python APIs.','https://example.invalid/project')")
    connection.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(702,402,'github','Synthetic repository','Built Python APIs.','https://github.com/Owner/Repo')")
    connection.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,filename,content_type,content) VALUES(703,402,'project','Synthetic PDF','Metadata only','synthetic.pdf','application/pdf',?)", (b'%PDF-SYNTHETIC-BLOB',))
    connection.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(704,403,'project','Synthetic other owner','','https://example.invalid/other')")


def snapshot(connection):
    return {name: [tuple(row) for row in connection.execute(f'SELECT * FROM {name} ORDER BY rowid')]
            for name in ('skills', 'candidates', 'companies', 'job_openings', 'swipe_decisions', 'notifications', 'match_audit', 'profile_materials')}


class EvidenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='recruitifi-storage-test-')
        self.addCleanup(self.directory.cleanup)
        location = patch.object(database, 'DB_PATH', Path(self.directory.name) / 'synthetic.sqlite3')
        location.start()
        self.addCleanup(location.stop)
        for target in ('socket.socket.connect', 'socket.getaddrinfo'):
            guard = patch(target, side_effect=AssertionError('Live network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        model = patch.object(semantic, 'EmbeddingClient')
        encoder = model.start().return_value
        self.addCleanup(model.stop)
        encoder.embed.side_effect = lambda texts, **_: [[1.0] + [0.0]*383 for text in texts]
        with database.connect() as connection:
            seed(connection, database.SCHEMA_PATH.read_text())

    def project(self, connection, material_id=701):
        row = connection.execute('SELECT * FROM profile_materials WHERE id=?', (material_id,)).fetchone()
        return semantic.match_project_material(row, connection=connection, synthetic_data=True)

    def github(self, connection, material_id=702):
        row = connection.execute('SELECT * FROM profile_materials WHERE id=?', (material_id,)).fetchone()
        repository = github_fixtures.validate_github_repository_url(row['url'])
        base = f"/repos/{repository['owner']}/{repository['repository']}"
        routes = {base: github_fixtures.Response(github_fixtures.metadata(repository))}
        entries = []
        for path, text in [('README.md', b'Synthetic Python project'), ('package.json', b'{"dependencies":{"react":"1"}}'), ('src/main.py', b'pass')]:
            entry, blob = github_fixtures.entry(path, text)
            entries.append(entry)
            routes[base + '/git/blobs/' + entry['sha']] = github_fixtures.Response(blob)
        routes[base + '/git/trees/main?recursive=1'] = github_fixtures.Response({'sha': 'a'*40, 'truncated': False, 'tree': entries})
        with patch.object(github_fetcher, '_open_connection', side_effect=lambda _: github_fixtures.Connection(routes, [])):
            return github_pipeline.analyze_github_material(row, connection=connection, synthetic_data=True)

    def test_additive_idempotent_upgrade_preserves_all_existing_records_and_blobs(self):
        legacy = database.SCHEMA_PATH.read_text().split('-- AI evidence storage:')[0]
        with patch.object(database, 'DB_PATH', Path(self.directory.name) / 'legacy.sqlite3'):
            with database.connect() as connection:
                seed(connection, legacy)
                before = snapshot(connection)
                for _ in range(3):
                    connection.executescript(database.SCHEMA_PATH.read_text())
                    self.assertEqual(snapshot(connection), before)
                self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(connection.execute('SELECT count(*) FROM evidence_analysis_runs').fetchone()[0], 0)

    def test_project_roundtrip_persists_across_connections_without_business_changes(self):
        with database.connect() as connection:
            before = snapshot(connection)
            report = self.project(connection)
            identifier, = storage.save_analysis(402, report, connection=connection)
            value = storage.get_analysis(402, identifier, connection=connection)
            self.assertEqual(snapshot(connection), before)
            self.assertEqual(value['model_id'], report['model'])
            self.assertEqual(value['model_revision'], report['revision'])
            self.assertEqual(len(value['sources']), len(report['fragments']))
            self.assertEqual(len(value['findings']), sum(len(f['matches']) for f in report['fragments']))
            self.assertTrue(all(f['review_status'] == 'unreviewed' for f in value['findings']))
            self.assertTrue(all(f['interpretation'] == 'semantic_relevance_only' for f in value['findings']))
            self.assertRegex(value['created_at'], r'^\d{4}-\d{2}-\d{2}T.*Z$')
        with database.connect() as connection:
            self.assertEqual(storage.get_analysis(402, identifier, connection=connection), value)

    def test_github_roundtrip_preserves_blob_references_and_separate_observations(self):
        with database.connect() as connection:
            report = self.github(connection)
            before = snapshot(connection)
            identifier, = storage.save_analysis(402, report, connection=connection)
            result = storage.get_analysis(402, identifier, connection=connection)
            self.assertEqual(snapshot(connection), before)
            self.assertEqual(result['analysis_kind'], 'github')
            self.assertEqual(result['semantic_status'], 'complete')
            self.assertEqual(result['retrieval_status'], 'retrieved')
            sources = {s['id']: s for s in result['sources']}
            for finding in result['findings']:
                source = sources[finding['source_id']]
                self.assertEqual(source['run_id'], identifier)
                if source['file_path']:
                    self.assertEqual(source['source_reference'], 'https://api.github.com/repos/Owner/Repo/git/blobs/' + source['blob_sha'])
                    self.assertEqual(source['tree_sha'], 'a'*40)
                if finding['finding_kind'] == 'observation':
                    self.assertIsNone(finding['similarity_score'])
                    self.assertEqual(source['excerpt'], '')
                else:
                    self.assertIsNotNone(finding['similarity_score'])
                    self.assertLessEqual(len(source['excerpt']), 160)
            self.assertEqual(sum(f['finding_kind'] == 'observation' for f in result['findings']), 2)

    def test_save_history_and_replace_only_one_run_preserve_identity_reset_review(self):
        with database.connect() as connection:
            report = self.project(connection)
            first, = storage.save_analysis(402, report, connection=connection)
            second, = storage.save_analysis(402, report, connection=connection)
            original = storage.get_analysis(402, first, connection=connection)
            connection.execute("UPDATE evidence_analysis_runs SET review_status='accepted',updated_at='2000-01-01' WHERE id=?", (first,))
            connection.execute("UPDATE evidence_skill_findings SET review_status='accepted' WHERE run_id=?", (first,))
            replacement = deepcopy(report)
            replacement['revision'] = 'synthetic-new-revision'
            replacement['fragments'] = replacement['fragments'][:1]
            self.assertEqual(storage.replace_analysis(402, first, replacement, connection=connection), first)
            after = storage.get_analysis(402, first, connection=connection)
            self.assertEqual(after['created_at'], original['created_at'])
            self.assertNotEqual(after['updated_at'], '2000-01-01')
            self.assertEqual(after['review_status'], 'unreviewed')
            self.assertTrue(all(f['review_status'] == 'unreviewed' for f in after['findings']))
            self.assertEqual(after['model_revision'], replacement['revision'])
            self.assertEqual(len(after['sources']), 1)
            self.assertEqual(storage.get_analysis(402, second, connection=connection)['model_revision'], report['revision'])

    def test_failed_replace_rolls_back_all_child_deletion_and_preserves_outer_transaction(self):
        with database.connect() as connection:
            report = self.project(connection)
            identifier, = storage.save_analysis(402, report, connection=connection)
            original = storage.get_analysis(402, identifier, connection=connection)
            connection.execute("UPDATE candidates SET full_name='Synthetic caller transaction' WHERE id=402")
            with patch.object(storage, '_entries', side_effect=sqlite3.IntegrityError('Synthetic insertion failure')):
                with self.assertRaises(sqlite3.IntegrityError):
                    storage.replace_analysis(402, identifier, report, connection=connection)
            self.assertEqual(storage.get_analysis(402, identifier, connection=connection), original)
            self.assertEqual(connection.execute('SELECT full_name FROM candidates WHERE id=402').fetchone()[0], 'Synthetic caller transaction')

    def test_caller_can_roll_back_successful_save(self):
        with database.connect() as connection:
            identifier, = storage.save_analysis(402, self.project(connection), connection=connection)
            self.assertTrue(connection.in_transaction)
            connection.rollback()
            with self.assertRaises(LookupError):
                storage.get_analysis(402, identifier, connection=connection)

    def test_delete_run_cascades_children_but_preserves_material_and_other_runs(self):
        with database.connect() as connection:
            report = self.project(connection)
            first, = storage.save_analysis(402, report, connection=connection)
            second, = storage.save_analysis(402, report, connection=connection)
            before = snapshot(connection)
            storage.delete_analysis(402, first, connection=connection)
            self.assertEqual(snapshot(connection), before)
            self.assertEqual(connection.execute('SELECT count(*) FROM evidence_sources WHERE run_id=?', (first,)).fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM evidence_skill_findings WHERE run_id=?', (first,)).fetchone()[0], 0)
            self.assertTrue(storage.get_analysis(402, second, connection=connection)['findings'])

    def test_existing_material_delete_path_cascades_every_associated_run(self):
        with database.connect() as connection:
            for _ in range(2):
                storage.save_analysis(402, self.project(connection), connection=connection)
            github_id, = storage.save_analysis(402, self.github(connection), connection=connection)
            before = snapshot(connection)
        delete_material(402, 701)  # Existing endpoint function + existing connect().
        with database.connect() as connection:
            after = snapshot(connection)
            for table in before:
                if table != 'profile_materials':
                    self.assertEqual(after[table], before[table], table)
            self.assertEqual(len(after['profile_materials']), len(before['profile_materials'])-1)
            self.assertEqual([r['id'] for r in storage.list_analysis_runs(402, connection=connection)], [github_id])
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(connection.execute('SELECT count(*) FROM evidence_skill_findings f LEFT JOIN evidence_sources s ON s.id=f.source_id WHERE s.id IS NULL').fetchone()[0], 0)

    def test_candidate_scope_and_material_identity_are_enforced(self):
        with database.connect() as connection:
            report = self.project(connection)
            identifier, = storage.save_analysis(402, report, connection=connection)
            for operation in (lambda: storage.save_analysis(403, report, connection=connection),
                              lambda: storage.get_analysis(403, identifier, connection=connection),
                              lambda: storage.delete_analysis(403, identifier, connection=connection),
                              lambda: storage.replace_analysis(403, identifier, report, connection=connection)):
                with self.assertRaises(LookupError):
                    operation()
            self.assertEqual(storage.list_analysis_runs(403, connection=connection), [])
            with self.assertRaises(ValueError):
                storage.replace_analysis(402, identifier, self.github(connection), connection=connection)

    def test_invalid_findings_excerpts_scores_and_review_status_do_not_write(self):
        with database.connect() as connection:
            base = self.project(connection)
            for field, invalid in [('skill_id', 999), ('skill_name', 'Invented'), ('review_status', 'accepted'),
                                   ('similarity_score', float('nan')), ('similarity_score', float('inf')),
                                   ('similarity_score', 1.1), ('similarity_score', True),
                                   ('supporting_excerpt', 'x'*161), ('supporting_excerpt', 'Wrong source'),
                                   ('excerpt_start', -1), ('material_id', 702)]:
                with self.subTest(field=field):
                    report = deepcopy(base)
                    report['fragments'][0]['matches'][0][field] = invalid
                    with self.assertRaises(ValueError):
                        storage.save_analysis(402, report, connection=connection)
            self.assertEqual(storage.list_analysis_runs(402, connection=connection), [])

    def test_immutable_github_and_owner_reference_validation(self):
        with database.connect() as connection:
            original = self.github(connection)
            for field, value in [('candidate_id', 403), ('material_id', 701), ('blob_sha', 'invalid'),
                                 ('file_path', '../secret'), ('source_reference', 'https://evil.invalid/file')]:
                report = deepcopy(original)
                report['materials'][0]['semantic_fragments'][0]['matches'][0]['source'][field] = value
                with self.assertRaises(ValueError):
                    storage.save_analysis(402, report, connection=connection)
            self.assertEqual(storage.list_analysis_runs(402, connection=connection), [])

    def test_empty_failed_and_limited_reports_are_stored_without_fake_findings(self):
        with database.connect() as connection:
            report = self.project(connection)
            report.update(status='failed', fragments=[], errors=[{'stage': 'embedding', 'code': 'unavailable'}], semantic_status='failed')
            identifier, = storage.save_analysis(402, report, connection=connection)
            saved = storage.get_analysis(402, identifier, connection=connection)
            self.assertEqual(saved['findings'], [])
            self.assertEqual(saved['sources'], [])
            self.assertEqual(saved['error_code'], 'unavailable')
            report.update(status='limited', coverage_limited=True)
            storage.replace_analysis(402, identifier, report, connection=connection)
            self.assertEqual(storage.get_analysis(402, identifier, connection=connection)['coverage_limited'], 1)

    def test_failed_stages_cannot_import_contradictory_findings(self):
        with database.connect() as connection:
            report = self.project(connection)
            report['semantic_status'] = 'failed'
            with self.assertRaises(ValueError):
                storage.save_analysis(402, report, connection=connection)
            report = self.github(connection)
            report['materials'][0]['retrieval_status'] = 'rate_limited'
            with self.assertRaises(ValueError):
                storage.save_analysis(402, report, connection=connection)
            self.assertEqual(storage.list_analysis_runs(402, connection=connection), [])

    def test_bounded_input_and_raw_report_content_are_not_persisted(self):
        with database.connect() as connection:
            report = self.project(connection)
            report.update(pdf_text='DO_NOT_STORE_FULL_DOCUMENT', embeddings=[[999]], files=[{'text': 'DO_NOT_STORE_REPOSITORY'}])
            storage.save_analysis(402, report, connection=connection)
            dump = '\n'.join(connection.iterdump())
            self.assertNotIn('DO_NOT_STORE_FULL_DOCUMENT', dump)
            self.assertNotIn('DO_NOT_STORE_REPOSITORY', dump)
            excessive = deepcopy(report)
            excessive['fragments'] *= 7
            with self.assertRaises(ValueError):
                storage.save_analysis(402, excessive, connection=connection)

    def test_foreign_keys_required_and_database_constraints_reject_invalid_scores(self):
        with database.connect() as connection:
            report = self.project(connection)
            connection.execute('PRAGMA foreign_keys=OFF')
            with self.assertRaisesRegex(ValueError, 'foreign_keys'):
                storage.save_analysis(402, report, connection=connection)
            connection.execute('PRAGMA foreign_keys=ON')
            identifier, = storage.save_analysis(402, report, connection=connection)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('UPDATE evidence_skill_findings SET similarity_score=2 WHERE run_id=?', (identifier,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE evidence_skill_findings SET review_status='verified' WHERE run_id=?", (identifier,))

    def test_multi_material_save_is_atomic_and_keeps_runs_separate(self):
        with database.connect() as connection:
            connection.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(705,402,'github','Synthetic second repo','','https://github.com/Owner/Other')")
            report = self.github(connection)
            report['materials'].append(self.github(connection, 705)['materials'][0])
            before = snapshot(connection)
            insert = storage._entries
            calls = 0
            def fail_second(*args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise sqlite3.IntegrityError('Synthetic failure in second material')
                return insert(*args)
            with patch.object(storage, '_entries', side_effect=fail_second):
                with self.assertRaises(sqlite3.IntegrityError):
                    storage.save_analysis(402, report, connection=connection)
            self.assertEqual(storage.list_analysis_runs(402, connection=connection), [])
            self.assertEqual(connection.execute('SELECT count(*) FROM evidence_sources').fetchone()[0], 0)
            identifiers = storage.save_analysis(402, report, connection=connection)
            self.assertEqual(len(identifiers), 2)
            self.assertEqual(snapshot(connection), before)
            self.assertEqual([row['material_id'] for row in storage.list_analysis_runs(402, connection=connection)], [705, 702])
            connection.execute('DELETE FROM profile_materials WHERE id=705')
            self.assertEqual([row['id'] for row in storage.list_analysis_runs(402, connection=connection)], identifiers[:1])

    def test_sources_cannot_be_assigned_to_another_run_by_direct_sql(self):
        with database.connect() as connection:
            first, = storage.save_analysis(402, self.project(connection), connection=connection)
            second, = storage.save_analysis(402, self.project(connection), connection=connection)
            source = storage.get_analysis(402, first, connection=connection)['sources'][0]['id']
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('UPDATE evidence_skill_findings SET source_id=? WHERE run_id=?', (source, second))

    def test_foreign_candidate_cannot_be_mixed_into_a_report_batch(self):
        with database.connect() as connection:
            report = self.github(connection)
            report['materials'][0]['candidate_id'] = 403
            with self.assertRaises(ValueError):
                storage.save_analysis(402, report, connection=connection)
            self.assertEqual(storage.list_analysis_runs(402, connection=connection), [])


if __name__ == '__main__':
    unittest.main()
