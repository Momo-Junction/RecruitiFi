"""Synthetic HTTP checks inside the offline container's loopback namespace.

Prints only aggregate metrics/statuses, never request text or returned embeddings.
"""
from concurrent.futures import ThreadPoolExecutor
import errno
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import time
import urllib.error
import urllib.request

from .model import MODEL_ID, REVISION

BASE = 'http://127.0.0.1:8080'
MARKER = 'SYNTHETIC_PRIVATE_TEXT_4C_NOT_FOR_LOGGING'
CGROUP = Path('/sys/fs/cgroup')


def request(path, value=None, raw=None, authenticated=True):
    data = json.dumps(value).encode() if value is not None else raw
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={'Content-Type': 'application/json', **({'Authorization':'Bearer '+os.environ['TALENTMATCH_EMBED_TOKEN']} if authenticated else {})} if data is not None else {})
    start = time.perf_counter()
    # Ignore host proxy environment; only explicit loopback is allowed here.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(req, timeout=90)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        value = json.loads(response.read(200000))
        return response.status, value, (time.perf_counter() - start) * 1000


def check_vectors(status, value, count):
    assert status == 200
    assert value['model'] == MODEL_ID and value['revision'] == REVISION
    assert len(value['embeddings']) == count
    for vector in value['embeddings']:
        assert len(vector) == 384 and all(math.isfinite(x) for x in vector)
        assert abs(sum(x*x for x in vector) - 1) < 1e-5


def main():
    assert platform.machine() == 'x86_64'
    assert (CGROUP / 'memory.max').read_text().strip() == '536870912'
    assert (CGROUP / 'memory.swap.max').read_text().strip() == '0'
    quota, period = map(int, (CGROUP / 'cpu.max').read_text().split())
    assert quota / period == 0.5
    probe = socket.socket()
    probe.settimeout(2)
    try:
        probe.connect(('1.1.1.1', 443))
    except OSError as error:
        assert error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM)
        network_denial = error.errno
    else:
        raise AssertionError('Outbound networking unexpectedly available')
    finally:
        probe.close()
    assert request('/healthz')[0] == 200
    assert request('/readyz')[0] == 200
    assert request('/embed', [MARKER], authenticated=False)[0] == 401
    check_vectors(*request('/embed', [MARKER])[:2], 1)
    for invalid in ([], [''], ['Synthetic'] * 4, {'texts': ['Synthetic']}, [False]):
        assert request('/embed', invalid)[0] == 422
    assert request('/embed', raw=b'["unfinished')[0] == 400
    assert request('/embed', ['python ' * 255])[0] == 422
    measurements = []
    for batch in (1, 3):
        for tokens in ('short', 256):
            text = 'Developed REST APIs using Python and FastAPI.' if tokens == 'short' else 'python ' * 254
            samples = []
            for _ in range(3):
                status, value, latency = request('/embed', [text] * batch)
                check_vectors(status, value, batch)
                samples.append(latency)
            measurements.append({'batch_size': batch, 'tokens': tokens, 'samples_ms': samples,
                                 'median_ms': statistics.median(samples)})
    # A maximum-length request occupies inference for >2 seconds under current emulation.
    # Deterministic queue synchronization is covered separately in the unit tests.
    with ThreadPoolExecutor(max_workers=1) as executor:
        active = executor.submit(request, '/embed', ['python ' * 254] * 3)
        # Real HTTP checks use a short delay after dispatch; deterministic gate semantics
        # (including cancellation) are covered separately by the unit tests.
        time.sleep(0.5)
        health_during_load = request('/healthz')[0]
        queued = request('/embed', ['Synthetic waiting request'])
        active_status, active_value, _ = active.result(timeout=90)
    check_vectors(active_status, active_value, 3)
    assert health_during_load == 200
    # Native faster hardware may complete the active call within the queue deadline.
    assert queued[0] in (200, 429)
    status = dict(line.split(':', 1) for line in Path('/proc/1/status').read_text().splitlines() if ':' in line)
    cpu = (CGROUP / 'cpu.stat').read_text().strip()
    result = {'architecture': platform.machine(), 'offline_probe_errno': network_denial,
              'model': MODEL_ID, 'revision': REVISION, 'measurements': measurements,
              'server_rss_bytes': int(status['VmRSS'].split()[0]) * 1024,
              'server_peak_rss_bytes': int(status['VmHWM'].split()[0]) * 1024,
              'container_peak_bytes': int((CGROUP / 'memory.peak').read_text()),
              'memory_events': (CGROUP / 'memory.events').read_text().strip(),
              'cpu_stat': cpu, 'health_during_inference': health_during_load,
              'waiting_request_status': queued[0], 'waiting_request_ms': queued[2],
              'negative_input_checks': 'PASS', 'normalized_embeddings': 'PASS'}
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
