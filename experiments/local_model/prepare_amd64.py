"""Online preparation only: download and verify the two pinned x86 artifacts."""
import json
from download_model import ROOT, REPOSITORY, REVISION, download


def main():
    manifest = json.loads((ROOT / 'amd64_model_manifest.json').read_text())
    assert manifest['repository'] == REPOSITORY
    assert manifest['revision'] == REVISION
    for expected in manifest['files']:
        actual = download(expected['path'])
        if actual != expected:
            raise RuntimeError(f'Artifact hash/size mismatch: {expected["path"]}')
    print('Pinned x86 model and tokenizer verified; ready for image build.')


if __name__ == '__main__':
    main()
