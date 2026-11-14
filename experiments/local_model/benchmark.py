"""Standalone CPU-only MiniLM benchmark. Run inside offline.sb, not via the app."""
import argparse
import errno
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import socket
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'models' / 'all-MiniLM-L6-v2'
for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                  TOKENIZERS_PARALLELISM='false', HF_HOME=str(ROOT / 'hf_cache'), CUDA_VISIBLE_DEVICES='')

DESCRIPTIONS = [
    'Developed REST APIs using Python and FastAPI.',
    'Built React interfaces using TypeScript.',
    'Created Docker container configurations.',
]
REQUIREMENTS = [
    'Python and FastAPI REST API development.',
    'React and TypeScript frontend development.',
    'Docker container configuration and deployment.',
    'Food hygiene and restaurant kitchen cleaning.',
]


def prove_os_network_denial():
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(1)
    try:
        connection.connect(('1.1.1.1', 443))
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EACCES):
            raise RuntimeError('OS-level network denial not proven') from error
        return {'blocked': True, 'errno': error.errno, 'mechanism': 'macOS sandbox-exec deny network*'}
    else:
        raise RuntimeError('Outbound connection unexpectedly succeeded; refusing benchmark')
    finally:
        connection.close()


def install_python_network_guard():
    attempts = []
    def blocked(*args, **kwargs):
        attempts.append('blocked_socket_operation')
        raise RuntimeError('Outbound networking is forbidden during this benchmark')
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.sendto = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked
    # Verify the Python guard too; clear these intentional probes from measured attempts.
    for operation in [lambda: socket.create_connection(('example.invalid', 443)),
                      lambda: socket.getaddrinfo('example.invalid', 443)]:
        try:
            operation()
        except RuntimeError:
            pass
        else:
            raise AssertionError('Python network guard did not block')
    attempts.clear()
    return attempts


def peak_mib():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 ** 2) if sys.platform == 'darwin' else peak / 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', choices=['torch', 'onnx', 'onnx-int8'], required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--batch-sizes', nargs='+', type=int, default=[1, 3, 16, 32])
    args = parser.parse_args()
    if any(size < 1 or size > 32 for size in args.batch_sizes):
        parser.error('Batch sizes must be between 1 and 32.')
    probe = prove_os_network_denial()
    attempts = install_python_network_guard()
    started = time.perf_counter()
    import numpy as np
    import psutil
    process = psutil.Process()
    baseline_rss = process.memory_info().rss / 1024 ** 2
    if args.runtime == 'torch':
        import torch
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        import_seconds = time.perf_counter() - started
        load_start = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(str(MODEL), local_files_only=True, trust_remote_code=False)
        model = AutoModel.from_pretrained(str(MODEL), local_files_only=True, trust_remote_code=False, use_safetensors=True).to('cpu').eval()
        assert all(parameter.device.type == 'cpu' for parameter in model.parameters())
        def encode(texts):
            inputs = tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors='pt')
            with torch.inference_mode():
                output = model(**inputs).last_hidden_state
                mask = inputs['attention_mask'].unsqueeze(-1).to(output.dtype)
                pooled = (output * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
            return normalized.numpy(), int(inputs['input_ids'].shape[1])
        provider = 'PyTorch CPU, one intra-op/inter-op thread'
        artifact = 'model.safetensors'
    else:
        import onnxruntime as ort
        ort.disable_telemetry_events()
        from tokenizers import Tokenizer
        import_seconds = time.perf_counter() - started
        load_start = time.perf_counter()
        tokenizer = Tokenizer.from_file(str(MODEL / 'tokenizer.json'))
        tokenizer.enable_truncation(max_length=256)
        tokenizer.enable_padding(direction='right', pad_id=0, pad_type_id=0, pad_token='[PAD]')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        artifact = 'onnx/model.onnx' if args.runtime == 'onnx' else 'onnx/model_qint8_arm64.onnx'
        session = ort.InferenceSession(str(MODEL / artifact), sess_options=options, providers=['CPUExecutionProvider'])
        assert session.get_providers() == ['CPUExecutionProvider']
        input_names = {item.name for item in session.get_inputs()}
        assert input_names <= {'input_ids', 'attention_mask', 'token_type_ids'}
        def encode(texts):
            encoded = tokenizer.encode_batch(texts)
            values = {'input_ids': np.asarray([e.ids for e in encoded], dtype=np.int64),
                      'attention_mask': np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                      'token_type_ids': np.asarray([e.type_ids for e in encoded], dtype=np.int64)}
            tokens = session.run(None, {key: value for key, value in values.items() if key in input_names})[0]
            assert tokens.ndim == 3 and tokens.shape[-1] == 384
            mask = values['attention_mask'][..., None].astype(np.float32)
            pooled = (tokens * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
            normalized = pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)
            return normalized, int(values['input_ids'].shape[1])
        provider = session.get_providers()
    load_seconds = time.perf_counter() - load_start
    ready_seconds = time.perf_counter() - started
    rss_after_load = process.memory_info().rss / 1024 ** 2
    first_start = time.perf_counter()
    samples, _ = encode(DESCRIPTIONS + REQUIREMENTS)
    first_ms = (time.perf_counter() - first_start) * 1000
    assert samples.shape == (7, 384) and np.isfinite(samples).all()
    similarities = samples[:3] @ samples[3:].T
    cases = []
    for profile in ['short', 'max_256_tokens']:
        for batch_size in args.batch_sizes:
            texts = [DESCRIPTIONS[i % 3] for i in range(batch_size)] if profile == 'short' else [
                ('This synthetic project uses Python FastAPI REST APIs for a demonstration. ' * 80) for _ in range(batch_size)]
            for _ in range(3):
                _, tokens = encode(texts)
            repeats = 30 if profile == 'short' else 15
            timings = []
            cpu_start, wall_start = time.process_time(), time.perf_counter()
            for _ in range(repeats):
                tick = time.perf_counter()
                embeddings, tokens = encode(texts)
                timings.append((time.perf_counter() - tick) * 1000)
                assert np.isfinite(embeddings).all()
            wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
            cases.append({'profile': profile, 'batch_size': batch_size, 'tokens_per_sequence_padded': tokens,
                          'repeats': repeats, 'median_ms': statistics.median(timings),
                          'p95_ms': float(np.percentile(timings, 95)), 'min_ms': min(timings),
                          'cpu_seconds': cpu, 'wall_seconds': wall, 'cpu_percent_one_core': cpu / wall * 100,
                          'current_rss_mib': process.memory_info().rss / 1024 ** 2, 'peak_rss_mib': peak_mib()})
            print(f'{args.runtime}: {profile} batch={batch_size} tokens={tokens} median={cases[-1]["median_ms"]:.3f} ms peak={peak_mib():.1f} MiB', flush=True)
    assert not attempts, f'Unexpected network attempts during runtime import/loading/inference: {attempts}'
    result = {'runtime': args.runtime, 'python': sys.version, 'platform': platform.platform(),
              'architecture': platform.machine(), 'provider': provider, 'threads': 1, 'batch_sizes': args.batch_sizes,
              'model_artifact': artifact, 'model_revision': json.loads((ROOT / 'model_manifest.json').read_text())['revision'],
              'max_sequence_length': 256, 'embedding_dimensions': 384,
              'offline': {'HF_HUB_OFFLINE': os.environ['HF_HUB_OFFLINE'], 'TRANSFORMERS_OFFLINE': os.environ['TRANSFORMERS_OFFLINE'],
                          'os_probe': probe, 'python_guard_verified': True, 'network_attempts_during_inference': len(attempts)},
              'runtime_import_seconds': import_seconds, 'model_load_seconds': load_seconds,
              'startup_to_ready_seconds': ready_seconds, 'first_sample_batch_ms': first_ms,
              'baseline_rss_mib_after_numpy': baseline_rss, 'rss_after_model_load_mib': rss_after_load,
              'peak_process_rss_mib': peak_mib(), 'cases': cases,
              'synthetic_descriptions': DESCRIPTIONS, 'synthetic_requirements': REQUIREMENTS,
              'similarity_matrix': similarities.tolist(),
              'dependency_versions': {name: importlib.metadata.version(name) for name in
                                      ['torch', 'transformers', 'onnxruntime', 'tokenizers', 'numpy', 'psutil', 'safetensors', 'huggingface-hub']},
              'method': 'Fresh process per runtime; local files only; tokenizer + forward + attention-mask mean pooling + L2 normalization included in timings. Imports/model loading reported separately. No GPU/MPS/CoreML.'}
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
