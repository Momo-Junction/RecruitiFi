"""Mocked APIs/workers on disposable SQLite; no model, GitHub or live database."""
import asyncio
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI

from . import database, test_evidence_storage as fixtures
from .evidence import api, jobs, semantic_matching as semantic
from .evidence.embedding_client import EmbeddingServiceError

TOKEN = 'synthetic-test-token-not-a-real-secret-123456'


class EvidenceAPITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='recruitifi-api-synthetic-')
        self.addCleanup(temporary.cleanup)
        for target, value in [('backend.database.DB_PATH', Path(temporary.name)/'synthetic.sqlite3')]:
            guard = patch(target, value)
            guard.start()
            self.addCleanup(guard.stop)
        environment = patch.dict('os.environ', {'TALENTMATCH_AI_SYNTHETIC_DEMO': '1',
            'TALENTMATCH_AI_DEMO_TOKEN': TOKEN, 'TALENTMATCH_AI_SYNTHETIC_CANDIDATES': '402,403,406'})
        environment.start()
        self.addCleanup(environment.stop)
        for target in ('socket.socket.connect', 'socket.getaddrinfo'):
            guard = patch(target, side_effect=AssertionError('Live network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        encoder = patch.object(semantic, 'EmbeddingClient')
        instance = encoder.start().return_value
        self.encoder = instance
        instance.embed.side_effect = lambda texts, **_: [[1.0]+[0.0]*383 for text in texts]
        self.addCleanup(encoder.stop)
        github = patch.object(jobs, 'analyze_github_material', side_effect=lambda row, **kw: fixtures.EvidenceStorageTests.github(None, kw['connection']))
        self.github = github.start()
        self.addCleanup(github.stop)
        with database.connect() as connection:
            fixtures.seed(connection, database.SCHEMA_PATH.read_text())
            connection.execute("INSERT INTO candidates SELECT 406,'SYNTHETIC-406',full_name,'406@example.invalid',has_cv,has_portfolio,languages,needs_visa_sponsorship,skills FROM candidates WHERE id=402")
            connection.execute("INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(706,406,'project','Synthetic','','https://example.invalid')")
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.error = None

        def execute(job, path, deadline, cancelled):
            self.entered.set()
            while not self.release.wait(0.01):
                if cancelled():
                    return {'error': 'cancelled'}
                if time.time() >= deadline:
                    return {'error': 'timeout'}
            if self.error:
                if isinstance(self.error, Exception):
                    raise self.error
                return {'error': self.error}
            try:
                return {'report': jobs.analyze_material(job, deadline)}
            except EmbeddingServiceError as error:
                return {'error': error.code}

        self.manager = jobs.AnalysisManager(execute=execute)
        self.app = FastAPI()
        self.app.include_router(api.router)
        self.app.state.evidence_jobs = self.manager

    async def asyncTearDown(self):
        self.release.set()
        await asyncio.to_thread(self.manager.close)

    async def request(self, method, path, body=None, *, token=TOKEN, account=None, raw=None, headers=()):
        data = json.dumps(body).encode() if body is not None else raw or b''
        messages = []
        async def receive():
            return {'type': 'http.request', 'body': data, 'more_body': False}
        async def send(message):
            messages.append(message)
        values = [(b'content-type', b'application/json'), *headers]
        if token is not None:
            values.append((b'x-recruitifi-ai-token', token.encode()))
        if account:
            values.append((b'x-recruitifi-demo-account', account.encode()))
        await self.app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': b'',
            'root_path': '', 'headers': values, 'client': ('127.0.0.1', 1), 'server': ('test', 80)}, receive, send)
        output = b''.join(message.get('body', b'') for message in messages)
        self.last_headers = dict(messages[0].get('headers', []))
        return messages[0]['status'], json.loads(output) if output else None

    async def start(self, candidate=402, material=701, **kwargs):
        return await self.request('POST', f'/api/candidates/{candidate}/materials/{material}/analysis', **kwargs)

    async def finished(self, job_id, candidate=402):
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            status, result = await self.request('GET', f'/api/candidates/{candidate}/analysis-jobs/{job_id}')
            self.assertEqual(status, 200)
            if result['status'] not in jobs.ACTIVE:
                await asyncio.to_thread(self.manager.future.result, 2)
                return result
            await asyncio.sleep(0.01)
        self.fail('Synthetic worker did not finish')

    async def test_disabled_by_default_and_missing_config_fail_closed(self):
        with patch.dict('os.environ', TALENTMATCH_AI_SYNTHETIC_DEMO='0'):
            self.assertEqual((await self.start())[0], 404)
        for name in ('TALENTMATCH_AI_DEMO_TOKEN', 'TALENTMATCH_AI_SYNTHETIC_CANDIDATES'):
            with patch.dict('os.environ', {name: ''}):
                self.assertEqual((await self.start())[0], 503)
        self.assertFalse(self.entered.is_set())

    async def test_role_selection_is_not_authentication(self):
        for account in (None, 'talent-001', 'organizer-001'):
            self.assertEqual((await self.start(token=None, account=account))[0], 403)
        self.assertEqual((await self.start(token='wrong', account='talent-001'))[0], 403)
        self.assertEqual((await self.start(headers=[(b'x-recruitifi-ai-token', b'ambiguous')]))[0], 403)
        self.assertFalse(self.entered.is_set())

    async def test_operator_allowlist_and_existing_demo_owner_checks(self):
        with patch.dict('os.environ', TALENTMATCH_AI_SYNTHETIC_CANDIDATES='406'):
            self.assertEqual((await self.start())[0], 403)
        for account in ('talent-002', 'employer-001', 'organizer-001'):
            self.assertEqual((await self.start(account=account))[0], 403)
        self.assertFalse(self.entered.is_set())

    async def test_background_project_results_history_delete_and_unchanged_records(self):
        with database.connect() as connection:
            before = fixtures.snapshot(connection)
        self.release.clear()
        start = time.monotonic()
        status, accepted = await self.start(body={'top_k': 2})
        self.assertEqual(status, 202)
        self.assertLess(time.monotonic()-start, 1)
        self.assertEqual((await self.request('GET', accepted['result_url']))[0], 202)
        self.assertEqual(self.last_headers[b'cache-control'], b'no-store')
        self.release.set()
        self.assertEqual((await self.finished(accepted['job_id']))['status'], 'completed')
        status, result = await self.request('GET', accepted['result_url'])
        self.assertEqual(status, 200)
        self.assertTrue(result['analysis']['findings'])
        self.assertTrue(all(f['review_status'] == 'unreviewed' for f in result['analysis']['findings']))
        self.assertTrue(all(f['skill_id'] in (1,3,4,5) for f in result['analysis']['findings']))
        self.assertEqual(len(result['analysis']['findings']), 4)
        history = (await self.request('GET', '/api/candidates/402/materials/701/analyses'))[1]
        self.assertEqual(len(history['runs']), 1)
        self.assertEqual((await self.request('DELETE', accepted['status_url']))[0], 200)
        self.assertEqual((await self.request('GET', accepted['status_url']))[0], 404)
        with database.connect() as connection:
            self.assertEqual(fixtures.snapshot(connection), before)
            self.assertEqual(connection.execute('SELECT count(*) FROM evidence_skill_findings').fetchone()[0], 0)

    async def test_global_and_candidate_concurrency_without_unbounded_queue(self):
        self.release.clear()
        status, first = await self.start()
        self.assertEqual(status, 202)
        for candidate, material in ((402,701), (403,704), (406,706)):
            self.assertEqual((await self.start(candidate,material))[0], 429)
            self.assertEqual(self.last_headers[b'retry-after'], b'1')
        self.assertEqual((await self.request('DELETE', first['status_url']))[0], 409)
        with database.connect() as connection:
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO evidence_analysis_jobs(id,candidate_id,material_id,top_k,status,lease_deadline) VALUES(?,403,704,3,'queued',?)", ('b'*32,time.time()+100))
        self.release.set()
        await self.finished(first['job_id'])

    async def test_other_candidates_cannot_read_or_delete_results(self):
        _, accepted = await self.start()
        await self.finished(accepted['job_id'])
        path = accepted['status_url'].replace('/402/', '/403/')
        for method, suffix in (('GET',''),('GET','/result'),('DELETE','')):
            self.assertEqual((await self.request(method, path+suffix))[0], 404)
        self.assertEqual((await self.start(403,701))[0], 404)

    async def test_github_and_pdf_dispatch_reuse_existing_adapters(self):
        status, accepted = await self.start(material=702)
        self.assertEqual(status, 202)
        await self.finished(accepted['job_id'])
        result = (await self.request('GET', accepted['result_url']))[1]['analysis']
        self.assertTrue(any(source['blob_sha'] for source in result['sources']))
        self.github.assert_called_once()
        evidence = {'material_id':703,'candidate_id':402,'project_title':'Synthetic PDF','project_description':'Metadata only',
                    'source_type':'uploaded_pdf','extraction_status':'extracted','external_content_status':'not_applicable',
                    'text_truncated':False,'pdf_text':'Synthetic Python evidence.'}
        with patch.object(jobs, 'extract_project_evidence', return_value=evidence) as extractor:
            _, accepted = await self.start(material=703)
            self.assertEqual((await self.finished(accepted['job_id']))['status'], 'completed')
            extractor.assert_called_once_with(402,703)

    async def test_input_limits_and_no_user_model_endpoint(self):
        for body in ({'top_k':0},{'top_k':6},{'top_k':True},{'model_url':'https://external.invalid'},['bad']):
            self.assertEqual((await self.start(body=body))[0], 422)
        self.assertEqual((await self.start(raw=b'{' ))[0], 422)
        self.assertEqual((await self.start(raw=b' '*513))[0], 413)
        self.assertEqual((await self.start(material=999))[0], 404)
        with database.connect() as connection:
            connection.execute("UPDATE profile_materials SET url='https://github.com/Owner' WHERE id=702")
            connection.execute("UPDATE profile_materials SET category='cv' WHERE id=701")
        self.assertEqual((await self.start(material=702))[0], 422)
        self.assertEqual((await self.start())[0], 422)
        self.assertFalse(self.entered.is_set())

    async def test_timeout_error_and_logging_are_sanitized(self):
        self.error = RuntimeError('SYNTHETIC_PRIVATE_TEXT_DO_NOT_LOG')
        with patch.object(logging.Logger, '_log') as log:
            _, accepted = await self.start()
            finished = await self.finished(accepted['job_id'])
        self.assertEqual(finished['error_code'], 'analysis_failed')
        self.assertNotIn('PRIVATE', json.dumps(finished))
        log.assert_not_called()
        self.error = 'timeout'
        _, accepted = await self.start()
        self.assertEqual((await self.finished(accepted['job_id']))['status'], 'timed_out')

    async def test_model_unavailability_is_reported_without_results(self):
        self.encoder.check_ready.side_effect = EmbeddingServiceError('unavailable')
        _, accepted = await self.start()
        finished = await self.finished(accepted['job_id'])
        self.assertEqual(finished['status'], 'failed')
        self.assertEqual(finished['error_code'], 'unavailable')
        self.assertIsNone((await self.request('GET', accepted['result_url']))[1]['analysis'])

    async def test_elapsed_job_deadline_releases_admission(self):
        self.release.clear()
        with patch.object(jobs,'JOB_SECONDS',0.03):
            _, accepted = await self.start()
            self.assertEqual((await self.finished(accepted['job_id']))['status'],'timed_out')
        self.release.set()
        _, next_job = await self.start()
        self.assertEqual((await self.finished(next_job['job_id']))['status'],'completed')

    async def test_oversize_pdf_is_rejected_before_background_loading(self):
        with database.connect() as connection:
            connection.execute('UPDATE profile_materials SET content=? WHERE id=703',(b'x'*(10*1024*1024+1),))
        self.assertEqual((await self.start(material=703))[0],413)
        self.assertFalse(self.entered.is_set())

    async def test_expired_worker_lease_is_recovered(self):
        with database.connect() as connection:
            connection.execute("INSERT INTO evidence_analysis_jobs(id,candidate_id,material_id,top_k,status,lease_deadline) VALUES(?,402,701,3,'running',?)", ('a'*32, time.time()-1))
        _, accepted = await self.start()
        await self.finished(accepted['job_id'])
        self.assertEqual((await self.request('GET', '/api/candidates/402/analysis-jobs/'+'a'*32))[1]['status'], 'interrupted')

    async def test_material_deletion_cancels_worker_and_prevents_stale_save(self):
        self.release.clear()
        _, accepted = await self.start()
        self.assertTrue(await asyncio.to_thread(self.entered.wait,1))
        with database.connect() as connection:
            connection.execute('DELETE FROM profile_materials WHERE id=701')
        self.assertEqual((await self.finished(accepted['job_id']))['status'], 'cancelled')
        self.assertEqual((await self.request('GET', accepted['result_url']))[0], 410)
        with database.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM evidence_analysis_runs').fetchone()[0], 0)

    async def test_disabling_feature_or_shutdown_cancels_admitted_work(self):
        self.release.clear()
        _, accepted = await self.start()
        self.assertTrue(await asyncio.to_thread(self.entered.wait,1))
        with patch.dict('os.environ', TALENTMATCH_AI_SYNTHETIC_DEMO='0'):
            await asyncio.to_thread(self.manager.close)
        self.assertEqual((await self.request('GET', accepted['status_url']))[1]['status'], 'cancelled')


class ProcessSupervisionTests(unittest.TestCase):
    def test_hard_deadline_terminates_worker(self):
        process, receiver, sender, context = Mock(), Mock(), Mock(), Mock()
        process.pid = 123
        process.is_alive.side_effect = [True,True,False]
        context.Pipe.return_value = (receiver,sender)
        context.Process.return_value = process
        with patch.object(jobs.multiprocessing,'get_context',return_value=context):
            result = jobs.execute_isolated({},'/tmp/synthetic',time.time()-1,lambda:False)
        self.assertEqual(result,{'error':'timeout'})
        process.terminate.assert_called_once()
        self.assertTrue(context.Process.call_args.kwargs['daemon'])
        receiver.close.assert_called_once()

    def test_child_has_absolute_orphan_deadline_and_sanitizes_exceptions(self):
        sender = Mock()
        with patch.object(jobs.signal,'signal'), patch.object(jobs.signal,'setitimer') as alarm, \
             patch.object(jobs,'analyze_material',side_effect=RuntimeError('PRIVATE CONTENT')), \
             patch.object(jobs.logging,'disable'), patch.object(database,'DB_PATH',Path('/tmp/not-opened')):
            jobs._child({},'/tmp/not-opened',time.time()+10,sender)
        alarm.assert_called_once()
        self.assertEqual(json.loads(sender.send_bytes.call_args.args[0]),{'error':'analysis_failed'})

    def test_main_registers_routes(self):
        from .main import app
        self.assertIn('/api/candidates/{candidate_id}/materials/{material_id}/analysis', app.openapi()['paths'])

    def test_real_spawn_roundtrip_with_empty_synthetic_evidence_needs_no_model(self):
        with tempfile.TemporaryDirectory(prefix='recruitifi-spawn-synthetic-') as directory, \
             patch.object(database, 'DB_PATH', Path(directory)/'synthetic.sqlite3'), \
             patch.dict('os.environ', {'TALENTMATCH_AI_SYNTHETIC_DEMO':'1', 'TALENTMATCH_AI_DEMO_TOKEN':TOKEN,
                                      'TALENTMATCH_AI_SYNTHETIC_CANDIDATES':'402'}):
            with database.connect() as connection:
                fixtures.seed(connection, database.SCHEMA_PATH.read_text())
                connection.execute("UPDATE profile_materials SET title='',description='' WHERE id=701")
            payload = jobs.execute_isolated({'candidate_id':402,'material_id':701,'top_k':3},
                database.DB_PATH, time.time()+10, lambda:False)
            self.assertEqual(payload['report']['status'], 'no_evidence')


if __name__ == '__main__':
    unittest.main()
