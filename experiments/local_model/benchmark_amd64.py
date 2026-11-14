"""Bounded, synthetic, offline CPU benchmark; no application imports or service."""
import argparse
import errno
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import socket
import statistics
import time

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'models' / 'all-MiniLM-L6-v2'
CGROUP = Path('/sys/fs/cgroup')
ITERATIONS = 10


def cgroup():
    names = ('memory.current', 'memory.peak', 'memory.max', 'memory.swap.max',
             'memory.events', 'cpu.max', 'cpu.stat')
    return {name: (CGROUP / name).read_text().strip() for name in names}


def counters(value):
    return {line.split()[0]: int(line.split()[1]) for line in value.splitlines()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-size', type=int, choices=(1, 3), required=True)
    parser.add_argument('--max-tokens', type=int, choices=(128, 256), required=True)
    args = parser.parse_args()
    assert platform.machine() == 'x86_64', 'This test must run as Linux/amd64.'
    assert platform.system() == 'Linux'
    before = cgroup()
    assert int(before['memory.max']) == 512 * 1024 ** 2
    quota, period = map(int, before['cpu.max'].split())
    assert quota / period == 0.5
    assert before['memory.swap.max'] == '0', 'Swap must not mask the memory limit.'
    connection = socket.socket()
    connection.settimeout(2)
    try:
        connection.connect(('1.1.1.1', 443))
    except OSError as error:
        assert error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPERM, errno.EACCES), error
        network_probe = {'blocked': True, 'errno': error.errno, 'error': str(error)}
    else:
        raise AssertionError('OS-level network isolation failed')
    finally:
        connection.close()
    network_attempts = []

    def blocked(*unused_args, **unused_kwargs):
        network_attempts.append('blocked')
        raise RuntimeError('Network access forbidden in offline benchmark')

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked
    for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
        assert os.environ.get(name) == '1'
    manifest = json.loads((ROOT / 'amd64_model_manifest.json').read_text())
    for item in manifest['files']:
        path = MODEL / item['path']
        assert path.stat().st_size == item['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
    start = time.perf_counter()
    import numpy as np
    import psutil
    import onnxruntime as ort
    from tokenizers import Tokenizer
    imports_seconds = time.perf_counter() - start
    ort.disable_telemetry_events()
    start = time.perf_counter()
    tokenizer = Tokenizer.from_file(str(MODEL / 'tokenizer.json'))
    tokenizer.enable_truncation(max_length=args.max_tokens)
    tokenizer.enable_padding(pad_id=0, pad_token='[PAD]')
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(str(MODEL / 'onnx/model_quint8_avx2.onnx'),
                                   sess_options=options, providers=['CPUExecutionProvider'])
    assert session.get_providers() == ['CPUExecutionProvider']
    load_seconds = time.perf_counter() - start
    names = {item.name for item in session.get_inputs()}

    def encode(texts):
        assert 1 <= len(texts) <= args.batch_size
        encoded = tokenizer.encode_batch(texts)
        values = {'input_ids': [item.ids for item in encoded],
                  'attention_mask': [item.attention_mask for item in encoded],
                  'token_type_ids': [item.type_ids for item in encoded]}
        inputs = {name: np.asarray(values[name], dtype=np.int64) for name in names}
        assert inputs['input_ids'].shape[1] <= args.max_tokens
        output = session.run(None, inputs)[0]
        mask = inputs['attention_mask'][..., None]
        pooled = (output * mask).sum(axis=1) / mask.sum(axis=1)
        normalized = pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        assert normalized.shape == (len(texts), 384)
        assert np.isfinite(normalized).all()
        return normalized, inputs['input_ids'].shape[1]

    text = 'Developed REST APIs using Python and FastAPI with synthetic project tests. ' * 80
    texts = [text] * args.batch_size
    start = time.perf_counter()
    _, tokens = encode(texts)
    cold_ms = (time.perf_counter() - start) * 1000
    assert tokens == args.max_tokens
    cpu_before = counters(cgroup()['cpu.stat'])
    wall_start = time.perf_counter()
    process_start = time.process_time()
    latencies = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        encode(texts)
        latencies.append((time.perf_counter() - start) * 1000)
    process_seconds = time.process_time() - process_start
    wall_seconds = time.perf_counter() - wall_start
    cpu_after = counters(cgroup()['cpu.stat'])
    samples = ['Developed REST APIs using Python and FastAPI.',
               'Python and FastAPI REST API development.',
               'Food hygiene and restaurant kitchen cleaning.']
    vectors = np.concatenate([encode(samples[i:i + args.batch_size])[0]
                              for i in range(0, len(samples), args.batch_size)])
    similarities = vectors @ vectors.T
    assert similarities[0, 1] > similarities[0, 2]
    after = cgroup()
    assert not network_attempts
    result = {
        'architecture': platform.machine(), 'kernel': platform.release(), 'python': platform.python_version(),
        'uid': os.getuid(), 'batch_size': args.batch_size, 'max_tokens': args.max_tokens,
        'actual_tokens': tokens, 'iterations': ITERATIONS, 'imports_seconds': imports_seconds,
        'model_load_seconds': load_seconds, 'cold_inference_ms': cold_ms,
        'latency_ms': {'samples': latencies, 'median': statistics.median(latencies),
                       'min': min(latencies), 'max': max(latencies)},
        'process_rss_bytes': psutil.Process().memory_info().rss,
        'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        'cgroup_peak_bytes': int(after['memory.peak']),
        'cgroup_cpu_percent_one_core': (cpu_after['usage_usec'] - cpu_before['usage_usec']) / (wall_seconds * 10000),
        'process_cpu_percent_one_core': process_seconds / wall_seconds * 100,
        'inference_wall_seconds': wall_seconds,
        'cpu_stat_delta': {key: cpu_after[key] - cpu_before[key] for key in cpu_before},
        'cgroup_before': before, 'cgroup_after': after,
        'network_probe': network_probe, 'network_attempts_during_inference': network_attempts,
        'network_interfaces': Path('/proc/net/dev').read_text(),
        'similarities': {'matching_python': float(similarities[0, 1]), 'unrelated_kitchen': float(similarities[0, 2])},
        'providers': session.get_providers(), 'threads': {'intra_op': 1, 'inter_op': 1},
        'numpy_cpu_features': np._core._multiarray_umath.__cpu_features__,
        'dependencies': (ROOT / 'installed-requirements.txt').read_text(),
        'model_revision': manifest['revision'],
    }
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
