"""Create a minimal external binary-build context; no downloads or builds.

Retains service/Dockerfile and its input paths. The BuildConfig must already
select service/Dockerfile. The caller owns the printed temporary directory.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[1]
MODEL = Path('models/all-MiniLM-L6-v2')
ARTIFACTS = ('tokenizer.json', 'onnx/model_quint8_avx2.onnx')
# Exact inputs of the existing service/Dockerfile, including its container tests.
FILES = (
    'service/Dockerfile', 'service/Dockerfile.dockerignore',
    'requirements-linux.txt', 'requirements.lock', 'service/requirements.txt',
    'amd64_model_manifest.json',
    *(str(MODEL / name) for name in ARTIFACTS),
    'service/__init__.py', 'service/__main__.py', 'service/model.py',
    'service/app.py', 'service/test_service.py', 'service/http_smoke.py',
)


def verify(context):
    manifest = json.loads((context / 'amd64_model_manifest.json').read_text())
    if (manifest['repository'] != 'sentence-transformers/all-MiniLM-L6-v2'
            or manifest['revision'] != '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
            or len(manifest['files']) != len(ARTIFACTS)
            or {item['path'] for item in manifest['files']} != set(ARTIFACTS)):
        raise ValueError('Unexpected pinned model manifest.')
    for item in manifest['files']:
        path = context / MODEL / item['path']
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if path.stat().st_size != item['bytes'] or digest.hexdigest() != item['sha256']:
            raise ValueError(f'Model artifact hash/size mismatch: {item["path"]}')


def main():
    # Ignore a TMPDIR pointing into the checkout: binary contexts stay external.
    base = Path(tempfile.gettempdir()).resolve()
    if base.is_relative_to(REPOSITORY_ROOT):
        base = Path('/tmp').resolve()
    context = Path(tempfile.mkdtemp(prefix='recruitifi-ai-context-', dir=base)).resolve()
    try:
        if context.is_relative_to(REPOSITORY_ROOT):
            raise ValueError('Build context must be outside the repository.')
        for relative in FILES:
            source = ROOT / relative
            if not source.is_file() or not source.resolve().is_relative_to(ROOT):
                raise ValueError(f'Missing or external build input: {relative}')
            destination = context / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        verify(context)
        size = sum((context / relative).stat().st_size for relative in FILES)
    except Exception:
        shutil.rmtree(context)
        raise
    print(f'Context: {context}')
    print(f'Size: {size:,} bytes ({size / 1024**2:.2f} MiB), {len(FILES)} files')
    print('Pinned model/tokenizer SHA-256 and sizes: verified')


if __name__ == '__main__':
    main()
