"""Explicit one-time download; never used by the offline benchmark process."""
import datetime
from concurrent.futures import ThreadPoolExecutor
import re
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
REPOSITORY = 'sentence-transformers/all-MiniLM-L6-v2'
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
FILES = [
    'README.md', 'config.json', 'tokenizer.json', 'tokenizer_config.json',
    'special_tokens_map.json', 'vocab.txt', 'sentence_bert_config.json',
    'modules.json', 'config_sentence_transformers.json', '1_Pooling/config.json',
    'model.safetensors', 'onnx/model.onnx', 'onnx/model_qint8_arm64.onnx',
]
TARGET = ROOT / 'models' / 'all-MiniLM-L6-v2'
MAX_FILE_BYTES = 200 * 1024 * 1024


def get(url, offset=0):
    headers = {'User-Agent': 'RecruitiFi-local-benchmark/1.0'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)


def download(name):
    path = TARGET / name
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}'
    if not path.exists():
        temporary = path.with_name(path.name + '.partial')
        offset = temporary.stat().st_size if temporary.exists() else 0
        with get(url, offset) as response:
            total = None
            if response.status == 206:
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                if not match or int(match[1]) != offset:
                    raise RuntimeError('Invalid model download resume range')
                count, mode, total = offset, 'ab', int(match[3])
            else:
                count, mode = 0, 'wb'
            print(f'Downloading {name} from byte {count:,}', flush=True)
            with temporary.open(mode) as target:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > MAX_FILE_BYTES:
                        raise RuntimeError('Model artifact exceeds the experiment download cap')
                    target.write(chunk)
            if total is not None and count != total:
                raise RuntimeError('Incomplete model artifact download')
        temporary.replace(path)
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    print(f'{name}: {path.stat().st_size:,} bytes', flush=True)
    return {'path': name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def main():
    with get(f'https://huggingface.co/api/models/{REPOSITORY}/revision/{REVISION}') as response:
        metadata = json.load(response)
    assert metadata['sha'] == REVISION
    assert metadata['cardData']['license'] == 'apache-2.0'
    assert {name for name in FILES} <= {item['rfilename'] for item in metadata['siblings']}
    with ThreadPoolExecutor(max_workers=3) as workers:
        records = list(workers.map(download, FILES))
    manifest = {'repository': REPOSITORY, 'revision': REVISION, 'license': 'apache-2.0',
                'downloaded_at_utc': datetime.datetime.now(datetime.UTC).isoformat(),
                'files': records, 'total_bytes': sum(item['bytes'] for item in records),
                'download_source': f'https://huggingface.co/{REPOSITORY}/tree/{REVISION}',
                'note': 'Selected artifacts only; no pickle weights, training scripts or hosted inference calls.'}
    (ROOT / 'model_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Total: {manifest["total_bytes"]:,} bytes', flush=True)


if __name__ == '__main__':
    main()
