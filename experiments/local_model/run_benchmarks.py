"""Launch each runtime in a fresh OS-network-blocked process and summarize results."""
import datetime
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    if sys.platform != 'darwin':
        raise SystemExit('This launcher uses macOS sandbox-exec. Linux requires equivalent network isolation before running benchmark.py.')
    manifest = json.loads((ROOT / 'model_manifest.json').read_text())
    for item in manifest['files']:
        path = ROOT / 'models' / 'all-MiniLM-L6-v2' / item['path']
        assert path.stat().st_size == item['bytes']
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        assert digest == item['sha256'], f"Artifact hash mismatch: {item['path']}"
    results = ROOT / 'results'
    results.mkdir(exist_ok=True)
    all_results = []
    for runtime in ['torch', 'onnx', 'onnx-int8']:
        output = results / f'{runtime}.json'
        command = ['/usr/bin/sandbox-exec', '-f', str(ROOT / 'offline.sb'), sys.executable,
                   str(ROOT / 'benchmark.py'), '--runtime', runtime, '--output', str(output)]
        run = subprocess.run(command, text=True, capture_output=True, timeout=300)
        (results / f'{runtime}.stdout.txt').write_text(run.stdout)
        (results / f'{runtime}.stderr.txt').write_text(run.stderr)
        print(run.stdout, end='', flush=True)
        if run.returncode:
            print(run.stderr, file=sys.stderr)
            raise SystemExit(f'{runtime} failed with exit code {run.returncode}; no success result claimed.')
        all_results.append(json.loads(output.read_text()))
    # Only scalar matrix comparisons here; keep inference runtime processes isolated.
    baseline = all_results[0]['similarity_matrix']
    for result in all_results:
        result['max_similarity_delta_vs_torch'] = max(abs(a - b) for row_a, row_b in zip(result['similarity_matrix'], baseline) for a, b in zip(row_a, row_b))
        result['highest_similarity_skill_indices'] = [max(range(len(row)), key=row.__getitem__) for row in result['similarity_matrix']]
    def sysctl(name):
        return subprocess.check_output(['/usr/sbin/sysctl', '-n', name], text=True).strip()
    summary = {'timestamp_utc': datetime.datetime.now(datetime.UTC).isoformat(),
               'hardware': {'os': platform.platform(), 'architecture': platform.machine(),
                            'cpu': sysctl('machdep.cpu.brand_string'), 'logical_cpus': int(sysctl('hw.ncpu')),
                            'physical_memory_bytes': int(sysctl('hw.memsize'))},
               'rahti_reference_limits': {'cpu_millicores': 500, 'memory_mib': 512, 'replicas': 1},
               'results': all_results}
    (results / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('Summary saved to experiments/local_model/results/summary.json')


if __name__ == '__main__':
    main()
