"""Local-only, pinned CPU encoder. Submitted strings are untrusted data."""
import hashlib
import json
import os
from pathlib import Path

MODEL_ID = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
ROOT = Path(__file__).resolve().parents[1]
MAX_TOKENS = 256  # Includes [CLS] and [SEP].
MAX_CHARS = 8192

# Set before importing native/ML libraries; never use a hub/cache fallback.
for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                  TOKENIZERS_PARALLELISM='false', OTEL_SDK_DISABLED='true',
                  OTEL_TRACES_EXPORTER='none', OTEL_METRICS_EXPORTER='none', OTEL_LOGS_EXPORTER='none')


class InputError(ValueError):
    """Only constant, non-sensitive messages may be used here."""


def validate_texts(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise InputError('Expected a JSON array containing 1 to 3 text strings.')
    for index, text in enumerate(value):
        if not isinstance(text, str) or not text.strip():
            raise InputError(f'Text at index {index} must be a non-empty string.')
        if len(text) > MAX_CHARS:
            raise InputError(f'Text at index {index} exceeds the {MAX_CHARS}-character safety limit.')
        # Surrogates accepted by JSON are not valid Unicode for the tokenizer.
        if any(0xD800 <= ord(character) <= 0xDFFF for character in text):
            raise InputError(f'Text at index {index} contains invalid Unicode.')
    return value


class Encoder:
    def __init__(self, model_dir=None, manifest_path=None):
        directory = Path(model_dir or os.environ.get('LOCAL_MODEL_DIR', ROOT / 'models/all-MiniLM-L6-v2'))
        manifest = json.loads(Path(manifest_path or ROOT / 'amd64_model_manifest.json').read_text())
        if manifest['repository'] != MODEL_ID or manifest['revision'] != REVISION:
            raise RuntimeError('Unexpected model identity or revision.')
        expected = {'tokenizer.json', 'onnx/model_quint8_avx2.onnx'}
        if {item['path'] for item in manifest['files']} != expected:
            raise RuntimeError('Unexpected model manifest files.')
        for item in manifest['files']:
            path = directory / item['path']
            if path.stat().st_size != item['bytes']:
                raise RuntimeError('Local model artifact size mismatch.')
            digest = hashlib.sha256()
            with path.open('rb') as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != item['sha256']:
                raise RuntimeError('Local model artifact hash mismatch.')

        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        ort.disable_telemetry_events()
        self.np = np
        self.tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(directory / 'onnx/model_quint8_avx2.onnx'),
                                            sess_options=options, providers=['CPUExecutionProvider'])
        if self.session.get_providers() != ['CPUExecutionProvider']:
            raise RuntimeError('Only the CPU inference provider is permitted.')
        self.input_names = {item.name for item in self.session.get_inputs()}
        if self.input_names != {'input_ids', 'attention_mask', 'token_type_ids'}:
            raise RuntimeError('Unexpected model inputs.')

    def embed(self, texts):
        validate_texts(texts)
        encoded = self.tokenizer.encode_batch(texts)
        for index, item in enumerate(encoded):
            if len(item.ids) > MAX_TOKENS:
                raise InputError(f'Text at index {index} exceeds {MAX_TOKENS} tokens, including special tokens.')
        np = self.np
        width = max(len(item.ids) for item in encoded)
        values = {'input_ids': [item.ids + [0] * (width - len(item.ids)) for item in encoded],
                  'attention_mask': [item.attention_mask + [0] * (width - len(item.ids)) for item in encoded],
                  'token_type_ids': [item.type_ids + [0] * (width - len(item.ids)) for item in encoded]}
        inputs = {name: np.asarray(values[name], dtype=np.int64) for name in self.input_names}
        hidden = self.session.run(None, inputs)[0]
        mask = inputs['attention_mask'][..., None].astype(hidden.dtype)
        pooled = (hidden * mask).sum(axis=1) / mask.sum(axis=1)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        if pooled.shape != (len(texts), 384) or not np.isfinite(pooled).all() or not np.isfinite(norms).all() or (norms <= 0).any():
            raise RuntimeError('Invalid model output.')
        return (pooled / norms).tolist()
