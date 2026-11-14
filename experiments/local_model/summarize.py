"""Render measured JSON results; never invent missing benchmark values."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    summary = json.loads((ROOT / 'results/summary.json').read_text())
    manifest = json.loads((ROOT / 'model_manifest.json').read_text())
    results = summary['results']
    labels = {'torch': 'PyTorch FP32', 'onnx': 'ONNX FP32', 'onnx-int8': 'ONNX INT8 ARM64'}
    h = summary['hardware']
    lines = ['# MiniLM local CPU benchmark results', '', f"Measured: {summary['timestamp_utc']}", '',
             f"Host: {h['cpu']}, {h['architecture']}, {h['logical_cpus']} logical CPUs, {h['physical_memory_bytes'] / 1024 ** 3:.1f} GiB RAM; {h['os']}.", '',
             f"Model: `{manifest['repository']}`; revision `{manifest['revision']}`; license `{manifest['license']}`.", '',
             '## Local model artifacts', '', '| Artifact | Bytes | MiB |', '| --- | ---: | ---: |']
    weights = {r['model_artifact'] for r in results}
    for item in manifest['files']:
        if item['path'] in weights:
            lines.append(f"| {item['path']} | {item['bytes']:,} | {item['bytes'] / 1024 ** 2:.2f} |")
    shared = sum(item['bytes'] for item in manifest['files'] if item['path'] not in weights)
    lines.extend([f'| Shared tokenizer/config/card files | {shared:,} | {shared / 1024 ** 2:.2f} |',
                  f"| Total selected download | {manifest['total_bytes']:,} | {manifest['total_bytes'] / 1024 ** 2:.2f} |", '',
                  'Weights/caches/virtualenvs are ignored by Git. SHA-256 hashes are in model_manifest.json.', '',
                  '## Versions and startup', '', '| Package | Version |', '| --- | --- |'])
    for name, version in results[0]['dependency_versions'].items():
        lines.append(f'| {name} | {version} |')
    lines.extend(['', f"Python: {results[0]['python'].splitlines()[0]}", '',
                  '| Runtime | Import s | Model load s | Startup ready s | First 7-text inference ms | Peak process MiB |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |'])
    for r in results:
        lines.append(f"| {labels[r['runtime']]} | {r['runtime_import_seconds']:.3f} | {r['model_load_seconds']:.3f} | {r['startup_to_ready_seconds']:.3f} | {r['first_sample_batch_ms']:.2f} | {r['peak_process_rss_mib']:.1f} |")
    lines.extend(['', 'Peaks are OS high-water RSS for a fresh process, including imports, load, warmup and all measured batches. They are not merely model weight sizes. Model disk caches were warm; no cold-disk claim.', '',
                  '## Warm end-to-end inference', '', 'One inference thread, CPU only; tokenization + model forward + mean pooling + L2 normalization. Values are median / p95 milliseconds.', '',
                  '| Profile | Batch | Padded tokens | PyTorch FP32 ms | ONNX FP32 ms | ONNX INT8 ARM64 ms |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |'])
    for index, case in enumerate(results[0]['cases']):
        values = [r['cases'][index] for r in results]
        lines.append(f"| {case['profile']} | {case['batch_size']} | {case['tokens_per_sequence_padded']} | " + ' | '.join(f"{c['median_ms']:.2f} / {c['p95_ms']:.2f}" for c in values) + ' |')
    lines.extend(['', '| Runtime | Measured CPU % of one core (range) | Max current RSS MiB |', '| --- | ---: | ---: |'])
    for r in results:
        cpu = [c['cpu_percent_one_core'] for c in r['cases']]
        lines.append(f"| {labels[r['runtime']]} | {min(cpu):.1f}–{max(cpu):.1f} | {max(c['current_rss_mib'] for c in r['cases']):.1f} |")
    lines.extend(['', '100% CPU means one whole core. These runs do not enforce a 500m CPU quota.', '', '## Synthetic similarities', '',
                  'Columns: Python/FastAPI, React/TypeScript, Docker/deployment, food hygiene/kitchen cleaning. Rows are the three requested synthetic project descriptions.'])
    for r in results:
        lines.extend(['', f"### {labels[r['runtime']]}", '', '| Description | Python | React | Docker | Kitchen |', '| --- | ---: | ---: | ---: | ---: |'])
        for desc, row in zip(['REST APIs/Python/FastAPI', 'React/TypeScript interfaces', 'Docker container configuration'], r['similarity_matrix']):
            lines.append('| ' + desc + ' | ' + ' | '.join(f'{value:.4f}' for value in row) + ' |')
        lines.extend(['', f"Maximum cosine delta from PyTorch: {r['max_similarity_delta_vs_torch']:.8f}; highest-scoring requirement indices: {r['highest_similarity_skill_indices']}."])
    bounded = [json.loads(path.read_text()) for name in ['torch', 'onnx', 'onnx-int8']
               if (path := ROOT / 'results' / f'{name}-small.json').exists()]
    if bounded:
        lines.extend(['', '## Fresh processes with batches capped at 3', '',
                      '| Runtime | Peak MiB (only batches 1/3) | Short batch 3 median ms | 256-token batch 3 median ms |',
                      '| --- | ---: | ---: | ---: |'])
        for r in bounded:
            short = next(c for c in r['cases'] if c['batch_size'] == 3 and c['profile'] == 'short')
            long = next(c for c in r['cases'] if c['batch_size'] == 3 and c['profile'] == 'max_256_tokens')
            lines.append(f"| {labels[r['runtime']]} | {r['peak_process_rss_mib']:.1f} | {short['median_ms']:.2f} | {long['median_ms']:.2f} |")
        lines.extend(['', 'These are separate, fresh network-blocked processes. The first seven-text similarity check is included in startup, followed only by batch sizes 1 and 3. All completed offline with zero inference-time Python network attempts. Lower bounded-workload peaks do not include FastAPI or concurrent analysis/extraction.'])
    lines.extend(['', '## Offline verification' , '', 'Every runtime completed under macOS sandbox-exec with `(deny network*)`. Each first confirmed an outbound connect fails with EPERM/EACCES, then installed/tested Python socket guards before runtime import/loading. HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 were set; models were loaded from local files only. ONNX telemetry was disabled.'])
    for r in results:
        lines.append(f"- {labels[r['runtime']]}: OS block errno {r['offline']['os_probe']['errno']}; inference-time Python network attempts {r['offline']['network_attempts_during_inference']}.")
    lines.extend(['', 'No synthetic text was sent to hosted inference. Only package/model downloads used the network, before measurement.', '',
                  '## Rahti feasibility and limits', '',
                  'Reference deployment: one replica, 500m CPU limit, 512 MiB memory limit. The application and its retrieval/extraction allocations are NOT included in these isolated model-process measurements.'])
    for r in results:
        peak = r['peak_process_rss_mib']
        verdict = 'EXCEEDS the 512 MiB limit even in isolation' if peak >= 512 else f'below 512 MiB in isolation, leaving {512 - peak:.1f} MiB before any application/concurrency overhead'
        lines.append(f"- {labels[r['runtime']]}: {peak:.1f} MiB peak — {verdict} for the full stress workload.")
    lines.extend(['', 'These Mac arm64 numbers are not Linux/amd64 cgroup results. A 500m quota provides half a core of sustained capacity on the same CPU; per-request latency need not scale linearly because of quota periods and bursts. No Linux/Rahti inference, CPU throttling, combined FastAPI process, cold filesystem-cache run, concurrency test, or production deployment was performed.', '',
                  'Recommended next experiment: ONNX Runtime CPU, prioritizing INT8 for bounded-workload memory headroom, with bounded batches/concurrency, testing FP32 and an x86-targeted INT8 artifact on Linux/amd64 under actual 500m/512 MiB limits. ARM64 INT8 measurements do not certify AVX2 performance or parity. Treat 512 MiB as unverified until that combined workload test passes with headroom; do not infer fitness from small weight files alone.', '',
                  'These are semantic similarity examples, not calibrated skill scores or proof of candidate expertise. Nothing changes RecruitiFi matching/scoring or evidence tiers.', '',
                  'See README.md for reproduction, requirements.lock for exact dependencies, and results/*.json for raw measurements.'])
    (ROOT / 'RESULTS.md').write_text('\n'.join(lines) + '\n')
    print('Saved experiments/local_model/RESULTS.md')


if __name__ == '__main__':
    main()
