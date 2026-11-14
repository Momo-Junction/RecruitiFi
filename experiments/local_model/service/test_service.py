"""Synthetic only. No app/database imports, downloads or candidate documents."""
import asyncio
import io
import json
import logging
import math
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import httpx2
from starlette.testclient import TestClient

from .app import Admission, Overloaded, create_app
from .model import Encoder, InputError, MODEL_ID, REVISION, ROOT

TEST_TOKEN = 'synthetic-service-auth-test-only-123456789'


class FakeEncoder:
    def embed(self, texts):
        return [[1.0] + [0.0] * 383 for _ in texts]


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        environment = patch.dict(os.environ, TALENTMATCH_EMBED_TOKEN=TEST_TOKEN)
        environment.start()
        self.addCleanup(environment.stop)
        self.encoder = FakeEncoder()
        self.loader = Mock(return_value=self.encoder)
        self.app = create_app(self.loader, wait_seconds=0.05)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app), base_url='http://test', headers={'Authorization':'Bearer '+TEST_TOKEN})

    async def test_authentication_rejects_missing_wrong_and_duplicate_credentials(self):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app), base_url='http://test') as client:
            for headers in ({}, {'Authorization':'Bearer wrong'}, [('Authorization','Bearer '+TEST_TOKEN),('Authorization','Bearer '+TEST_TOKEN)]):
                response = await client.post('/embed', json=['Synthetic'], headers=headers)
                self.assertEqual(response.status_code,401)
                self.assertNotIn(TEST_TOKEN,response.text)
            self.assertEqual((await client.get('/healthz')).status_code,200)
            self.assertEqual((await client.get('/readyz')).status_code,200)

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def test_health_readiness_and_single_startup_load(self):
        for _ in range(2):
            self.assertEqual((await self.client.get('/healthz')).status_code, 200)
            self.assertEqual((await self.client.get('/readyz')).json()['revision'], REVISION)
            response = await self.client.post('/embed', json=['Synthetic Python project.'])
            self.assertEqual(response.status_code, 200)
        self.loader.assert_called_once_with()

    async def test_success_contract(self):
        response = await self.client.post('/embed', json=['Synthetic project.', 'Synthetic skill.'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        value = response.json()
        self.assertEqual(set(value), {'model', 'revision', 'embeddings'})
        self.assertEqual(value['model'], MODEL_ID)
        self.assertEqual(value['revision'], REVISION)
        self.assertEqual(len(value['embeddings']), 2)
        self.assertEqual(len(value['embeddings'][0]), 384)

    async def test_empty_and_wrong_types_rejected(self):
        for value in ([], [''], [' \n\t'], None, {}, {'texts': ['Synthetic']}, 'Synthetic', [1], [True], [[]], [{}]):
            with self.subTest(value_type=type(value).__name__):
                response = await self.client.post('/embed', content=json.dumps(value), headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 422)
                self.assertIn('error', response.json())

    async def test_batch_limits(self):
        for count in (1, 3):
            self.assertEqual((await self.client.post('/embed', json=['Synthetic'] * count)).status_code, 200)
        self.assertEqual((await self.client.post('/embed', json=['Synthetic'] * 4)).status_code, 422)

    async def test_malformed_json_and_unicode(self):
        for body in (b'["unfinished', b'not json', b'["\xff"]', b'[' * 2000):
            response = await self.client.post('/embed', content=body, headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status_code, 400)
        self.assertEqual((await self.client.post('/embed', content=b'["\\ud800"]', headers={'Content-Type': 'application/json'})).status_code, 422)

    async def test_content_type_and_body_character_limits(self):
        self.assertEqual((await self.client.post('/embed', content='[]')).status_code, 415)
        self.assertEqual((await self.client.post('/embed', content=b' ' * 32769, headers={'Content-Type': 'application/json'})).status_code, 413)
        self.assertEqual((await self.client.post('/embed', json=['a' * 8193])).status_code, 422)

    async def test_token_error_status(self):
        self.encoder.embed = Mock(side_effect=InputError('Text at index 0 exceeds 256 tokens, including special tokens.'))
        response = await self.client.post('/embed', json=['Synthetic'])
        self.assertEqual(response.status_code, 422)
        self.assertIn('256 tokens', response.json()['error']['message'])

    async def test_no_sensitive_request_or_failure_logging(self):
        marker = 'SYNTHETIC_REQUEST_MUST_NOT_APPEAR_IN_LOGS_4C'
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logging.getLogger().addHandler(handler)
        try:
            valid = await self.client.post('/embed', json=[marker])
            self.assertEqual(valid.status_code, 200)
            await self.client.post('/embed', content='["' + marker, headers={'Content-Type': 'application/json'})
            self.encoder.embed = Mock(side_effect=RuntimeError(marker))
            failed = await self.client.post('/embed', json=[marker])
            self.assertEqual(failed.status_code, 503)
            self.assertNotIn(marker, failed.text)
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertNotIn(marker, stream.getvalue())
        self.assertNotIn(str(valid.json()['embeddings']), stream.getvalue())

    async def test_api_concurrency_queue_timeout_and_health(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def slow(texts):
            calls.append(1)
            entered.set()
            release.wait(5)
            return FakeEncoder().embed(texts)

        self.encoder.embed = slow
        first = asyncio.create_task(self.client.post('/embed', json=['Synthetic']))
        second = None
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            second = asyncio.create_task(self.client.post('/embed', json=['Synthetic']))
            while self.app.state.admission.occupied != 2:
                await asyncio.sleep(0)
            third = await self.client.post('/embed', json=['Synthetic'])
            self.assertEqual(third.status_code, 429)
            self.assertEqual(third.headers['retry-after'], '1')
            self.assertEqual((await self.client.get('/healthz')).status_code, 200)
            self.assertEqual((await self.client.get('/readyz')).status_code, 200)
            self.assertEqual((await second).status_code, 429)
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            await first
            if second:
                await second
        self.assertEqual((await self.client.post('/embed', json=['Synthetic'])).status_code, 200)


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_client_does_not_release_running_slot(self):
        admission = Admission(wait_seconds=0.02)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def slow(value):
            calls.append(1)
            entered.set()
            release.wait(5)
            return value

        client = asyncio.create_task(admission.run(slow, 'synthetic'))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            client.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await client
            with self.assertRaises(Overloaded):
                await admission.run(slow, 'synthetic')
            self.assertEqual(len(calls), 1)
            self.assertEqual(admission.occupied, 1)
        finally:
            release.set()
            await admission.drain()
        self.assertEqual(admission.occupied, 0)

    async def test_waiter_can_succeed_without_overlapping_inference(self):
        gate = Admission(wait_seconds=1)
        active = 0
        peak = 0

        def work(value):
            nonlocal active, peak
            import time
            active += 1
            peak = max(peak, active)
            time.sleep(0.01)
            active -= 1
            return value

        self.assertEqual(await asyncio.gather(gate.run(work, 1), gate.run(work, 2)), [1, 2])
        self.assertEqual(peak, 1)


class StartupTests(unittest.TestCase):
    def test_missing_or_invalid_service_secret_fails_before_model_load(self):
        for token in ('','short','x'*32+'\n'):
            loader=Mock()
            with patch.dict(os.environ,TALENTMATCH_EMBED_TOKEN=token):
                with self.assertRaisesRegex(RuntimeError,'TALENTMATCH_EMBED_TOKEN'):
                    with TestClient(create_app(loader)):
                        pass
            loader.assert_not_called()

    def test_missing_model_files_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                Encoder(model_dir=directory)
            app = create_app(lambda: Encoder(model_dir=directory))
            with self.assertRaisesRegex(RuntimeError, 'Local model initialization failed'):
                with patch.dict(os.environ,TALENTMATCH_EMBED_TOKEN=TEST_TOKEN), TestClient(app):
                    pass

    def test_tampered_tokenizer_rejected_before_loading_model(self):
        with tempfile.TemporaryDirectory() as directory:
            text = bytearray((ROOT / 'models/all-MiniLM-L6-v2/tokenizer.json').read_bytes())
            text[0] ^= 1
            Path(directory, 'tokenizer.json').write_bytes(text)
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                Encoder(model_dir=directory)


class NotReadyTests(unittest.IsolatedAsyncioTestCase):
    async def test_not_ready_without_startup(self):
        app = create_app()
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url='http://test') as client:
            self.assertEqual((await client.get('/healthz')).status_code, 200)
            self.assertEqual((await client.get('/readyz')).status_code, 503)
            self.assertEqual((await client.post('/embed', json=['Synthetic'])).status_code, 401)


class RealModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A socket guard supplements OS network denial in the Docker/offline tests.
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')), \
             patch.object(socket, 'getaddrinfo', side_effect=AssertionError('DNS forbidden')):
            cls.encoder = Encoder()

    def test_real_dimensions_normalization_and_offline_inference(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')), \
             patch.object(socket, 'getaddrinfo', side_effect=AssertionError('DNS forbidden')):
            vectors = self.encoder.embed(['Developed REST APIs using Python and FastAPI.',
                                          'Python and FastAPI REST API development.',
                                          'Food hygiene and restaurant kitchen cleaning.'])
        self.assertEqual(len(vectors), 3)
        for vector in vectors:
            self.assertEqual(len(vector), 384)
            self.assertTrue(all(math.isfinite(x) for x in vector))
            self.assertAlmostEqual(sum(x*x for x in vector), 1.0, places=5)
        cosine = lambda a, b: sum(x*y for x, y in zip(a, b))
        self.assertGreater(cosine(vectors[0], vectors[1]), cosine(vectors[0], vectors[2]))

    def test_exact_token_boundary_accepted(self):
        text = 'python ' * 254
        self.assertEqual(len(self.encoder.tokenizer.encode(text).ids), 256)
        self.assertEqual(len(self.encoder.embed([text])[0]), 384)

    def test_oversized_tokens_rejected_without_model_execution(self):
        text = 'python ' * 255
        self.assertEqual(len(self.encoder.tokenizer.encode(text).ids), 257)
        with patch.object(self.encoder.session, 'run', wraps=self.encoder.session.run) as run:
            with self.assertRaisesRegex(InputError, 'index 1 exceeds 256 tokens'):
                self.encoder.embed(['Synthetic', text])
            run.assert_not_called()

    def test_real_engine_rechecks_batch_and_empty_limits(self):
        for value in ([], [''], ['Synthetic'] * 4):
            with self.assertRaises(InputError):
                self.encoder.embed(value)


if __name__ == '__main__':
    unittest.main()
