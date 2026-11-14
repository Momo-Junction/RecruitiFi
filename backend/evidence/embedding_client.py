"""Synthetic inference only. Loopback or one explicit internal Service; no proxies.

No logging, redirects, external inference, downloads, or stored requests/results.
The only internal hostname is recruitifi-ai, with explicit configuration and auth.
"""
import http.client
from contextlib import suppress
import json
import math
import ipaddress
import os
import re
import socket
import threading
import time

MODEL_ID = 'sentence-transformers/all-MiniLM-L6-v2'
MODEL_REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
DIMENSIONS = 384
MAX_REQUEST_BYTES = 16_384
MAX_RESPONSE_BYTES = 131_072
CONNECT_TIMEOUT = 2.0
READ_TIMEOUT = 30.0
REQUEST_TIMEOUT = 35.0
_SLOT = threading.BoundedSemaphore(1)
_URL = re.compile(r'http://(127\.0\.0\.1|localhost|\[::1\]):([0-9]{1,5})/embed', re.ASCII)
INTERNAL_HOST = 'recruitifi-ai'
_DNS_SLOT = threading.BoundedSemaphore(1)


def _internal_addresses(timeout):
    if not _DNS_SLOT.acquire(blocking=False):
        raise EmbeddingServiceError('busy')
    done, result = threading.Event(), {}
    def resolve():
        try:
            result['values'] = socket.getaddrinfo(INTERNAL_HOST, 8080, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        except Exception:
            result['values'] = []
        finally:
            _DNS_SLOT.release()
            done.set()
    try:
        threading.Thread(target=resolve, daemon=True, name='fixed-inference-dns').start()
    except Exception:
        _DNS_SLOT.release()
        raise EmbeddingServiceError('unavailable') from None
    if not done.wait(timeout):
        raise EmbeddingServiceError('timeout')
    values = result.get('values', [])
    if not values or len(values) > 8:
        raise EmbeddingServiceError('unsafe_destination')
    addresses = []
    networks = [ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','fc00::/7')]
    for family, _, _, _, address in values:
        try:
            ip = ipaddress.ip_address(address[0])
        except ValueError:
            raise EmbeddingServiceError('unsafe_destination') from None
        if family not in (socket.AF_INET, socket.AF_INET6) or '%' in address[0] or (len(address)>3 and address[3]) or not any(ip in n for n in networks):
            raise EmbeddingServiceError('unsafe_destination')
        addresses.append((family, address[0]))
    return addresses


class EmbeddingServiceError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(f'Local embedding service: {code}.')


class _Connection(http.client.HTTPConnection):
    def connect(self):
        if self.host == INTERNAL_HOST:
            started = time.monotonic()
            # Pin one vetted numeric address; no second DNS lookup or proxy path.
            family, numeric = _internal_addresses(self.timeout)[0]
            self.sock = socket.socket(family, socket.SOCK_STREAM)
            self.sock.settimeout(max(.001, self.timeout-(time.monotonic()-started)))
            self.sock.connect((numeric, self.port))
            return
        family = socket.AF_INET6 if self.host == '::1' else socket.AF_INET
        self.sock = socket.socket(family, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))  # Numeric loopback only; no second DNS lookup.


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate response key')
        value[key] = item
    return value


class EmbeddingClient:
    """Endpoint comes only from trusted process configuration, never evidence/URLs.

    Loopback or explicitly enabled http://recruitifi-ai:8080/embed only.
    Internal HTTP relies on cluster isolation; use synthetic data only.
    """
    def __init__(self):
        configured = os.environ.get('TALENTMATCH_EMBED_URL', '')
        token = os.environ.get('TALENTMATCH_EMBED_TOKEN', '')
        internal = configured == f'http://{INTERNAL_HOST}:8080/embed' and os.environ.get('TALENTMATCH_EMBED_INTERNAL_HOST') == INTERNAL_HOST
        if token and (not 32 <= len(token) <= 256 or any(not 33 <= ord(c) <= 126 for c in token)):
            raise EmbeddingServiceError('unsafe_configuration')
        if internal:
            if not token:
                raise EmbeddingServiceError('unsafe_configuration')
            self.host, self.port, self.token = INTERNAL_HOST, 8080, token
            return
        match = _URL.fullmatch(configured)
        if not match or not 1 <= int(match[2]) <= 65535:
            raise EmbeddingServiceError('unsafe_configuration')
        self.host = '::1' if match[1] == '[::1]' else '127.0.0.1'
        self.port = int(match[2])
        self.token = token

    def _request(self, method, path, body, deadline):
        if (method, path) not in (('GET', '/readyz'), ('POST', '/embed')):
            raise EmbeddingServiceError('unsafe_request')
        if not _SLOT.acquire(blocking=False):
            raise EmbeddingServiceError('busy')
        connection = None
        transport_socket = None
        response = None
        timer = None
        expired = threading.Event()
        end = min(deadline, time.monotonic() + REQUEST_TIMEOUT)

        def abort():
            expired.set()
            sock = transport_socket if transport_socket is not None else connection.sock if connection is not None else None
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        try:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise EmbeddingServiceError('timeout')
            connection = _Connection(self.host, self.port, timeout=min(CONNECT_TIMEOUT, remaining))
            timer = threading.Timer(remaining, abort)
            timer.daemon = True
            timer.start()  # Also bounds slow/trickling headers and bodies, not just idle reads.
            connection.connect()
            transport_socket = connection.sock
            connection.sock.settimeout(min(READ_TIMEOUT, max(0.001, end - time.monotonic())))
            connection.request(method, path, body=body, headers={
                'Accept': 'application/json', 'Accept-Encoding': 'identity',
                'Content-Type': 'application/json', 'Connection': 'close',
                **({'Authorization': 'Bearer '+self.token} if self.token and path == '/embed' else {})})
            response = connection.getresponse()
            if response.status != 200:
                code = {401: 'unauthorized', 403: 'unauthorized', 429: 'overloaded', 422: 'input_rejected', 503: 'unavailable'}.get(response.status, 'unexpected_status')
                if 300 <= response.status < 400:
                    code = 'redirect_rejected'
                raise EmbeddingServiceError(code)
            headers = {}
            for name, value in response.getheaders():
                name = name.lower()
                if name in headers:
                    raise EmbeddingServiceError('invalid_response')
                headers[name] = value
            if headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                raise EmbeddingServiceError('invalid_response')
            if headers.get('content-encoding', 'identity').lower() != 'identity':
                raise EmbeddingServiceError('invalid_response')
            length = headers.get('content-length')
            transfer = headers.get('transfer-encoding')
            if transfer is not None and (transfer.lower() != 'chunked' or length is not None):
                raise EmbeddingServiceError('invalid_response')
            if length is not None and (not length.isascii() or not length.isdigit() or len(length) > 6 or int(length) > MAX_RESPONSE_BYTES):
                raise EmbeddingServiceError('response_too_large')
            payload = bytearray()
            while True:
                if expired.is_set() or time.monotonic() >= end:
                    raise EmbeddingServiceError('timeout')
                chunk = response.read1(min(4096, MAX_RESPONSE_BYTES + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise EmbeddingServiceError('response_too_large')
            if expired.is_set() or time.monotonic() >= end:
                raise EmbeddingServiceError('timeout')
            if length is not None and len(payload) != int(length):
                raise EmbeddingServiceError('invalid_response')
            try:
                return json.loads(payload.decode('utf-8'), object_pairs_hook=_object,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeError, RecursionError):
                raise EmbeddingServiceError('invalid_response') from None
        except EmbeddingServiceError:
            raise
        except (TimeoutError, socket.timeout):
            raise EmbeddingServiceError('timeout') from None
        except (OSError, http.client.HTTPException):
            raise EmbeddingServiceError('timeout' if expired.is_set() else 'unavailable') from None
        finally:
            try:
                if timer is not None:
                    timer.cancel()
                    timer.join()
                if response is not None:
                    with suppress(OSError):
                        response.close()
                if connection is not None:
                    with suppress(OSError):
                        connection.close()
            finally:
                _SLOT.release()

    def check_ready(self, *, deadline):
        value = self._request('GET', '/readyz', None, deadline)
        if not isinstance(value, dict) or value != {'status': 'ready', 'model': MODEL_ID, 'revision': MODEL_REVISION}:
            raise EmbeddingServiceError('model_not_ready')

    def embed(self, texts, *, deadline):
        if not isinstance(texts, list) or not 1 <= len(texts) <= 3 or any(
            not isinstance(text, str) or not text.strip() or len(text) > 8192 for text in texts
        ):
            raise EmbeddingServiceError('invalid_input')
        try:
            body = json.dumps(texts, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (ValueError, UnicodeError):
            raise EmbeddingServiceError('invalid_input') from None
        if len(body) > MAX_REQUEST_BYTES:
            raise EmbeddingServiceError('request_too_large')
        value = self._request('POST', '/embed', body, deadline)
        if (not isinstance(value, dict) or set(value) != {'model', 'revision', 'embeddings'}
                or value['model'] != MODEL_ID or value['revision'] != MODEL_REVISION):
            raise EmbeddingServiceError('invalid_response')
        vectors = value['embeddings']
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingServiceError('invalid_response')
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != DIMENSIONS:
                raise EmbeddingServiceError('invalid_response')
            try:
                if any(type(item) not in (int, float) or not math.isfinite(item) for item in vector):
                    raise ValueError()
                norm = math.hypot(*vector)
                if not math.isfinite(norm) or abs(norm - 1.0) > 0.001:
                    raise ValueError()
            except (ValueError, OverflowError):
                raise EmbeddingServiceError('invalid_response') from None
        return vectors
