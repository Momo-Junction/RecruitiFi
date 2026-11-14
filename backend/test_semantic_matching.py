"""Synthetic SQLite/PDF fixtures and mocked HTTP only; no model or network needed."""
from io import BytesIO
from contextlib import closing
import json
import logging
import math
import os
import socket
import sqlite3
import threading
import time
import unittest
from unittest.mock import Mock, patch

from .database import SCHEMA_PATH
from .evidence import embedding_client as ec, semantic_matching as sm
from .test_evidence import material, synthetic_pdf


def vector(index=0, sign=1.0):
    result = [0.0] * ec.DIMENSIONS
    result[index] = sign
    return result


def embedded(vectors):
    return {'model': ec.MODEL_ID, 'revision': ec.MODEL_REVISION, 'embeddings': vectors}


class Response:
    def __init__(self, value=None, *, raw=None, status=200, headers=None):
        self.raw = json.dumps(value).encode() if raw is None else raw
        self.stream = BytesIO(self.raw)
        self.status = status
        self.headers = headers if headers is not None else [('Content-Type', 'application/json'), ('Content-Length', str(len(self.raw)))]

    def getheaders(self):
        return self.headers

    def read1(self, size):
        return self.stream.read(size)

    def close(self):
        self.stream.close()


class OfflineTest(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.getaddrinfo'):
            p = patch(target, side_effect=AssertionError('Tests must not use networking'))
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'TALENTMATCH_EMBED_URL': 'http://127.0.0.1:18082/embed',
                                   'HTTP_PROXY': 'http://proxy.invalid:80', 'HTTPS_PROXY': 'http://proxy.invalid:80'})
        p.start()
        self.addCleanup(p.stop)

    def transport(self, responses):
        connection = Mock()
        connection.getresponse.side_effect = responses
        p = patch.object(ec, '_Connection', return_value=connection)
        factory = p.start()
        self.addCleanup(p.stop)
        return connection, factory

    def assert_service_error(self, code, operation):
        with self.assertRaises(ec.EmbeddingServiceError) as error:
            operation()
        self.assertEqual(error.exception.code, code)


class ClientTests(OfflineTest):
    def test_internal_destination_requires_exact_opt_in_and_secret(self):
        token='synthetic-internal-service-test-token-123456'
        with patch.dict(os.environ,TALENTMATCH_EMBED_URL='http://recruitifi-ai:8080/embed',TALENTMATCH_EMBED_INTERNAL_HOST='recruitifi-ai',TALENTMATCH_EMBED_TOKEN=token):
            client=ec.EmbeddingClient()
            self.assertEqual((client.host,client.port),('recruitifi-ai',8080))
            connection,_=self.transport([Response(embedded([vector()]))])
            client.embed(['Synthetic'],deadline=time.monotonic()+3)
            self.assertEqual(connection.request.call_args.kwargs['headers']['Authorization'],'Bearer '+token)
            for changes in ({'TALENTMATCH_EMBED_TOKEN':''},{'TALENTMATCH_EMBED_INTERNAL_HOST':'evil.invalid'},
                {'TALENTMATCH_EMBED_URL':'http://recruitifi-ai.evil.com:8080/embed'},
                {'TALENTMATCH_EMBED_URL':'http://recruitifi-ai:8081/embed'},
                {'TALENTMATCH_EMBED_URL':'http://recruitifi-ai:8080/embed?x=1'}):
                with patch.dict(os.environ,changes):
                    self.assert_service_error('unsafe_configuration',ec.EmbeddingClient)

    def test_internal_dns_pins_private_addresses_and_rejects_mixed_answers(self):
        def answer(ip):
            return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',(ip,8080))]
        with patch.object(ec.socket,'getaddrinfo',return_value=answer('172.30.1.2')) as dns, patch.object(ec.socket,'socket') as factory:
            connection=ec._Connection('recruitifi-ai',8080,timeout=2)
            connection.connect()
            factory.return_value.connect.assert_called_once_with(('172.30.1.2',8080))
            self.assertEqual(dns.call_args.args,('recruitifi-ai',8080))
        for ip in ('127.0.0.1','169.254.169.254','8.8.8.8','0.0.0.0'):
            with patch.object(ec.socket,'getaddrinfo',return_value=answer('172.30.1.2')+answer(ip)):
                self.assert_service_error('unsafe_destination',lambda: ec._internal_addresses(1))

    def test_authentication_failure_is_sanitized(self):
        self.transport([Response(status=401)])
        self.assert_service_error('unauthorized',lambda: ec.EmbeddingClient().embed(['Synthetic'],deadline=time.monotonic()+3))

    def test_internal_dns_wait_is_bounded_and_outstanding_resolvers_are_capped(self):
        entered, release = threading.Event(), threading.Event()
        def stalled(*args, **kwargs):
            entered.set()
            release.wait(2)
            return []
        with patch.object(ec.socket,'getaddrinfo',side_effect=stalled):
            try:
                self.assert_service_error('timeout',lambda: ec._internal_addresses(.01))
                self.assertTrue(entered.is_set())
                self.assert_service_error('busy',lambda: ec._internal_addresses(.01))
            finally:
                release.set()
                # Wait for the one bounded resolver to release its global slot.
                for _ in range(100):
                    if ec._DNS_SLOT.acquire(blocking=False):
                        ec._DNS_SLOT.release()
                        break
                    time.sleep(.001)

    def test_only_configured_literal_loopback_allowed(self):
        for host, numeric in [('127.0.0.1', '127.0.0.1'), ('localhost', '127.0.0.1'), ('[::1]', '::1')]:
            with patch.dict(os.environ, TALENTMATCH_EMBED_URL=f'http://{host}:8080/embed'):
                self.assertEqual(ec.EmbeddingClient().host, numeric)
        bad = ['', 'https://127.0.0.1:8080/embed', 'http://127.1:8080/embed',
               'http://2130706433:8080/embed', 'http://127.0.0.1.evil.com:8080/embed',
               'http://169.254.169.254:80/embed', 'http://10.0.0.1:8080/embed',
               'http://model-service:8080/embed', 'http://api.openai.com:443/embed',
               'http://user:pass@localhost:8080/embed', 'http://localhost/embed',
               'http://localhost:0/embed', 'http://localhost:65536/embed',
               'http://localhost:8080/embed/', 'http://localhost:8080/embed?x=1',
               'http://localhost:8080/embed#x', 'http://localhost:8080/../embed',
               'http://localhost:8080/%65mbed', 'http://localhost:8080/embed\n',
               'http://[::ffff:127.0.0.1]:8080/embed']
        for url in bad:
            with self.subTest(url=url), patch.dict(os.environ, TALENTMATCH_EMBED_URL=url):
                self.assert_service_error('unsafe_configuration', ec.EmbeddingClient)

    def test_numeric_socket_connection_avoids_dns_and_proxy(self):
        with patch.object(ec.socket, 'socket') as factory:
            connection = ec._Connection('127.0.0.1', 8080, timeout=2)
            connection.connect()
            factory.return_value.connect.assert_called_once_with(('127.0.0.1', 8080))
            factory.return_value.settimeout.assert_called_once_with(2)
            connection.close()

    def test_request_shape_and_response_validation(self):
        connection, factory = self.transport([Response(embedded([vector(), vector(1)]))])
        value = ec.EmbeddingClient().embed(['Synthetic evidence', 'Synthetic skill'], deadline=time.monotonic() + 3)
        self.assertEqual(value, [vector(), vector(1)])
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ('POST', '/embed'))
        self.assertEqual(json.loads(kwargs['body']), ['Synthetic evidence', 'Synthetic skill'])
        self.assertEqual(kwargs['headers']['Accept-Encoding'], 'identity')
        self.assertEqual(factory.call_args.args, ('127.0.0.1', 18082))
        connection.close.assert_called_once()

    def test_readiness_and_model_identity(self):
        self.transport([Response({'status': 'ready', 'model': ec.MODEL_ID, 'revision': ec.MODEL_REVISION}),
                        Response({'status': 'ready', 'model': 'wrong', 'revision': ec.MODEL_REVISION})])
        client = ec.EmbeddingClient()
        client.check_ready(deadline=time.monotonic() + 3)
        self.assert_service_error('model_not_ready', lambda: client.check_ready(deadline=time.monotonic() + 3))

    def test_redirect_and_service_errors_never_followed(self):
        connection, _ = self.transport([Response(status=status) for status in (302, 429, 422, 503, 404)])
        client = ec.EmbeddingClient()
        for code in ('redirect_rejected', 'overloaded', 'input_rejected', 'unavailable', 'unexpected_status'):
            self.assert_service_error(code, lambda: client.embed(['Synthetic'], deadline=time.monotonic() + 3))
        self.assertEqual(connection.request.call_count, 5)

    def test_malformed_headers_json_and_oversized_streams(self):
        responses = [Response(raw=b'{bad'), Response(raw=b'\xff'), Response(raw=b'[' * 2000),
                     Response(raw=b'{"model":1,"model":2}'), Response(raw=b'{"x":NaN}'),
                     Response(embedded([vector()]), headers=[('Content-Type', 'text/html')]),
                     Response(headers=[('Content-Type', 'application/json'), ('Content-Encoding', 'gzip')]),
                     Response(headers=[('Content-Type', 'application/json'), ('Content-Type', 'application/json')]),
                     Response(headers=[('Content-Type', 'application/json'), ('Content-Length', '100')]),
                     Response(headers=[('Content-Type', 'application/json'), ('Content-Length', '999999999')]),
                     Response(raw=b' ' * (ec.MAX_RESPONSE_BYTES + 1), headers=[('Content-Type', 'application/json')])]
        self.transport(responses)
        client = ec.EmbeddingClient()
        for _ in responses:
            with self.assertRaises(ec.EmbeddingServiceError):
                client.embed(['Synthetic'], deadline=time.monotonic() + 3)

    def test_invalid_embedding_shapes_types_norms_and_identity(self):
        values = [None, [], embedded([]), embedded([[1.0]]), embedded([vector(), vector()]),
                  embedded([[0.0] * 384]), embedded([['bad'] * 384]), embedded([[True] + [0] * 383]),
                  embedded([[1e308] * 384]), embedded([[2.0] + [0.0] * 383]),
                  {**embedded([vector()]), 'revision': 'wrong'}, {**embedded([vector()]), 'model': 'wrong'},
                  embedded([[float('inf')] + [0.0] * 383]), embedded([[float('nan')] + [0.0] * 383])]
        self.transport([Response(value) for value in values])
        client = ec.EmbeddingClient()
        for value in values:
            with self.subTest(value_type=type(value).__name__):
                self.assert_service_error('invalid_response', lambda: client.embed(['Synthetic'], deadline=time.monotonic() + 3))

    def test_input_and_request_size_limits_before_network(self):
        client = ec.EmbeddingClient()
        for value in ([], [''], ['Synthetic'] * 4, 'Synthetic', [False], ['x' * 8193], ['\ud800']):
            self.assert_service_error('invalid_input', lambda: client.embed(value, deadline=time.monotonic() + 3))
        self.assert_service_error('request_too_large', lambda: client.embed(['x' * 8192] * 3, deadline=time.monotonic() + 3))

    def test_deadline_and_network_failures_are_sanitized_and_release_slot(self):
        connection, _ = self.transport([Response(embedded([vector()]))])
        client = ec.EmbeddingClient()
        self.assert_service_error('timeout', lambda: client.embed(['Synthetic'], deadline=time.monotonic() - 1))
        connection.connect.side_effect = TimeoutError('SYNTHETIC_SECRET')
        self.assert_service_error('timeout', lambda: client.embed(['Synthetic'], deadline=time.monotonic() + 3))
        connection.connect.side_effect = OSError('SYNTHETIC_SECRET')
        self.assert_service_error('unavailable', lambda: client.embed(['Synthetic'], deadline=time.monotonic() + 3))
        connection.connect.side_effect = None
        self.assertEqual(client.embed(['Synthetic'], deadline=time.monotonic() + 3), [vector()])

    def test_one_process_wide_request_slot(self):
        self.assertTrue(ec._SLOT.acquire(blocking=False))
        try:
            self.assert_service_error('busy', lambda: ec.EmbeddingClient().embed(['Synthetic'], deadline=time.monotonic() + 3))
        finally:
            ec._SLOT.release()

    def test_watchdog_interrupts_a_trickling_response(self):
        connection, _ = self.transport([])
        released = threading.Event()
        connection.sock.shutdown.side_effect = lambda *_: released.set()

        def slow_headers():
            if not released.wait(1):
                raise AssertionError('Watchdog did not interrupt the request')
            raise OSError('closed')

        connection.getresponse.side_effect = slow_headers
        with patch.object(ec, 'REQUEST_TIMEOUT', 0.03):
            self.assert_service_error('timeout', lambda: ec.EmbeddingClient().embed(['Synthetic'], deadline=time.monotonic() + 3))
        self.assertTrue(released.is_set())

    def test_watchdog_keeps_socket_when_http_connection_detaches_it(self):
        connection, _ = self.transport([])
        response = Response()
        released = threading.Event()
        original = connection.sock
        original.shutdown.side_effect = lambda *_: released.set()

        def headers():
            connection.sock = None  # HTTPConnection does this for Connection: close.
            return response

        def stalled_body(_):
            if not released.wait(1):
                raise AssertionError('Body deadline was not enforced')
            return b''

        connection.getresponse.side_effect = headers
        response.read1 = stalled_body
        with patch.object(ec, 'REQUEST_TIMEOUT', 0.03):
            self.assert_service_error('timeout', lambda: ec.EmbeddingClient().embed(['Synthetic'], deadline=time.monotonic() + 3))
        self.assertTrue(response.stream.closed)


class MatchingTests(OfflineTest):
    def setUp(self):
        super().setUp()
        self.connection = sqlite3.connect(':memory:')
        self.addCleanup(self.connection.close)
        self.connection.executescript(SCHEMA_PATH.read_text())
        self.connection.executemany('INSERT INTO skills(id,esco_uri,name,category) VALUES(?,?,?,?)',
                                    [(17, 'urn:synthetic:python', 'Python', 'Development'),
                                     (29, 'urn:synthetic:docker', 'Docker', 'Development'),
                                     (88, 'urn:synthetic:react', 'React', 'Development')])
        self.connection.commit()

    def response_client(self, mapping=None):
        self.requests = []
        mapping = mapping or {'Python': vector(), 'Docker': vector(1), 'React': vector(2)}
        connection, _ = self.transport([])

        def request(method, path, **kwargs):
            self.requests.append((method, path, kwargs.get('body')))

        def response():
            method, path, body = self.requests[-1]
            if path == '/readyz':
                return Response({'status': 'ready', 'model': ec.MODEL_ID, 'revision': ec.MODEL_REVISION})
            return Response(embedded([mapping.get(text, vector()) for text in json.loads(body)]))

        connection.request.side_effect = request
        connection.getresponse.side_effect = response
        return connection

    def compare(self, row=None, **kwargs):
        return sm.match_project_material(row or material(url='https://example.invalid/synthetic', content=None,
                                         filename=None, content_type=None, title='Synthetic Python project', description=''),
                                         connection=self.connection, synthetic_data=True, **kwargs)

    def test_existing_sparse_ids_cosine_top_k_and_attribution_without_writes(self):
        self.response_client()
        before = self.connection.total_changes
        statements = []
        self.connection.set_trace_callback(statements.append)
        result = self.compare(top_k=2)
        match = result['fragments'][0]['matches'][0]
        self.assertEqual((match['skill_id'], match['skill_name'], match['similarity_score']), (17, 'Python', 1.0))
        self.assertEqual(match['material_id'], 7)
        self.assertEqual(match['evidence_source_type'], 'project_link')
        self.assertEqual(match['supporting_excerpt'], 'Synthetic Python project')
        self.assertEqual(match['review_status'], 'unreviewed')
        self.assertEqual(match['interpretation'], 'semantic_relevance_only')
        self.assertEqual(len(result['fragments'][0]['matches']), 2)
        self.assertEqual(result['external_content_status'], 'not_analyzed')
        self.assertEqual(self.connection.total_changes, before)
        self.assertTrue(all(sql.startswith(('SELECT', 'PRAGMA table_info')) for sql in statements))
        sent = [json.loads(body) for method, _, body in self.requests if method == 'POST']
        self.assertEqual(sent[0], ['Python', 'Docker', 'React'])
        self.assertEqual(sent[1], ['Synthetic Python project'])

    def test_ties_use_ids_and_negative_scores_are_not_percentages(self):
        self.response_client({'Python': vector(0, -1), 'Docker': vector(0, -1), 'React': vector(0, -1)})
        matches = self.compare()['fragments'][0]['matches']
        self.assertEqual([m['skill_id'] for m in matches], [17, 29, 88])
        self.assertTrue(all(m['similarity_score'] == -1 for m in matches))

    def test_pdf_text_uses_extractor_and_exact_source_offsets(self):
        self.response_client()
        text = 'Synthetic Python project ' * 15
        result = self.compare(material(title='', description='', skill_id=None, content=synthetic_pdf((text,))))
        original = sm.extract_project_material(material(title='', description='', skill_id=None, content=synthetic_pdf((text,))))['pdf_text']
        self.assertGreater(len(result['fragments']), 1)
        for fragment in result['fragments']:
            match = fragment['matches'][0]
            self.assertEqual(fragment['evidence_field'], 'pdf_text')
            self.assertEqual(match['evidence_source_type'], 'uploaded_pdf')
            self.assertEqual(match['supporting_excerpt'], original[fragment['start']:fragment['end']][:160])
            self.assertEqual(match['supporting_excerpt'], original[match['excerpt_start']:match['excerpt_end']])
            self.assertEqual(match['evidence_field'], 'pdf_text')

    def test_failed_pdf_does_not_fabricate_content_but_can_compare_metadata(self):
        self.response_client()
        result = self.compare(material(title='Synthetic metadata only', description='', content=b'bad PDF'))
        self.assertEqual(result['extraction_status'], 'malformed_pdf')
        self.assertEqual([part['evidence_field'] for part in result['fragments']], ['project_title'])

    def test_scanned_empty_evidence_and_empty_catalog_make_no_model_calls(self):
        with patch.object(sm, 'EmbeddingClient') as client:
            result = self.compare(material(title='', description='', content=synthetic_pdf(image_only=True)))
            self.assertEqual(result['status'], 'no_evidence')
            client.assert_not_called()
            self.connection.execute('DELETE FROM skills')  # Disposable fixture only.
            self.assertEqual(self.compare()['status'], 'no_skills')
            client.assert_not_called()

    def test_fragment_coverage_and_batching_are_bounded(self):
        self.response_client()
        result = self.compare(material(title='', description='a' * 2000, url='https://example.invalid', content=None))
        self.assertTrue(result['coverage_limited'])
        self.assertEqual(result['status'], 'limited')
        self.assertEqual(len(result['fragments']), 6)
        for method, _, body in self.requests:
            if method == 'POST':
                self.assertLessEqual(len(json.loads(body)), 3)
                self.assertLessEqual(len(body), ec.MAX_REQUEST_BYTES)

    def test_optional_real_description_column_and_catalog_limits(self):
        with closing(sqlite3.connect(':memory:')) as connection:
            connection.execute('CREATE TABLE skills(id INTEGER, name TEXT, description TEXT)')
            connection.execute('INSERT INTO skills VALUES(42,?,?)', ('Python', 'Synthetic description'))
            self.assertEqual(sm._catalog(connection)[0]['text'], 'Python: Synthetic description')
            connection.execute('UPDATE skills SET description=?', ('a' * 401,))
            with self.assertRaises(ValueError):
                sm._catalog(connection)
        self.connection.executemany('INSERT INTO skills VALUES(?,?,?,?)',
                                    [(1000+i, f'urn:synthetic:{i}', f'Skill {i}', 'Test') for i in range(100)])
        with self.assertRaisesRegex(ValueError, '100-skill'):
            self.compare()

    def test_synthetic_opt_in_top_k_and_analysis_concurrency(self):
        with self.assertRaisesRegex(ValueError, 'synthetic'):
            sm.match_project_material(material(), connection=self.connection)
        for top_k in (0, 6, True, 1.5):
            with self.assertRaises(ValueError):
                self.compare(top_k=top_k)
        self.assertTrue(sm._ANALYSIS_SLOT.acquire(blocking=False))
        try:
            self.assert_service_error('busy', self.compare)
        finally:
            sm._ANALYSIS_SLOT.release()

    def test_failure_returns_no_fake_success_or_sensitive_logs(self):
        connection = self.response_client()
        connection.getresponse.side_effect = OSError('SYNTHETIC_PRIVATE_CONTENT')
        with patch.object(logging.Logger, '_log') as log:
            self.assert_service_error('unavailable', self.compare)
        log.assert_not_called()

    def test_analysis_budget_is_forwarded_and_enforced(self):
        self.response_client()
        with patch.object(sm, 'ANALYSIS_SECONDS', -1):
            self.assert_service_error('timeout', self.compare)


if __name__ == '__main__':
    unittest.main()
