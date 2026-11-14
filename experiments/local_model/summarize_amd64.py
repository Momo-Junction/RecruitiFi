"""Render the recorded container measurements; never infer missing measurements."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    data = json.loads((ROOT / 'results-linux-amd64/summary.json').read_text())
    tests = data['tests']
    manifest = json.loads((ROOT / 'amd64_model_manifest.json').read_text())
    env = data['environment']
    size_lines = (ROOT / 'results-linux-amd64/image-size.txt').read_text().splitlines()
    disk_usage = size_lines[1].split()[2]
    rows = []
    for item in tests:
        m = item.get('measurement')
        if not m:
            rows.append(f"| {item['case']} | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | {item.get('state', {}).get('ExitCode', '?')} / {item.get('state', {}).get('OOMKilled', '?')} |")
            continue
        rows.append(f"| {item['case']} | {m['cgroup_peak_bytes']/2**20:.1f} | {m['process_peak_rss_bytes']/2**20:.1f} | {m['model_load_seconds']:.3f} | {m['latency_ms']['median']:.1f} | {m['cgroup_cpu_percent_one_core']:.1f}% | {item['state']['ExitCode']} / {item['state']['OOMKilled']} |")
    measured = [item['measurement'] for item in tests if 'measurement' in item]
    complete = len(tests) == 8 and len(measured) == 8 and all(item['state']['ExitCode'] == 0 and not item['state']['OOMKilled'] for item in tests)
    max_peak = max((m['cgroup_peak_bytes'] for m in measured), default=0) / 2**20
    lines = [
        '# Linux/amd64 INT8 feasibility results', '',
        f"Eight-case local experiment: **{'PASS' if complete else 'INCOMPLETE / FAILURE'}**. Native Linux/amd64 / CSC validation: **NOT TESTED**.", '',
        f"Tested image: Linux/{env['image_architecture']}; Python reports x86_64. Host: {env['host_system']} {env['host_machine']}; Docker daemon: {env['daemon_os']}/{env['daemon_architecture']} (Engine {env['docker_version']}).",
        '**These measurements use x86 emulation on Apple Silicon, not native amd64 hardware.** Exposed AVX2 capability is recorded in each JSON. Do not extrapolate these wall times to CSC CPUs.', '',
        'Every case has a fresh container: 512 MiB cgroup limit, no swap, 0.5 CPU, network none, read-only rootfs, arbitrary non-root UID 1000620000, one intra-op and one inter-op thread, CPU provider only. Cases run sequentially, twice each; ten warm iterations plus cold inference and a synthetic similarity check. Maximum token lengths are actually reached.', '',
        f"Model: `{manifest['repository']}`, revision `{manifest['revision']}`, Apache-2.0. Upstream x86 `onnx/model_quint8_avx2.onnx`: **{manifest['model_bytes']:,} bytes ({manifest['model_bytes']/2**20:.2f} MiB)**; with tokenizer: {manifest['model_and_tokenizer_bytes']:,} bytes ({manifest['model_and_tokenizer_bytes']/2**20:.2f} MiB).",
        'Quantization: dynamic UINT8 activations/weights with MatMulInteger (48 nodes), opset 14; both vector/per-channel and scalar scales observed. This is the published AVX2 artifact, not an ARM artifact or local re-quantization. Exporter/calibration settings beyond what is observable in the graph are unverified. Hashes and graph details are in `amd64_model_manifest.json`.', '',
        f"Image ID: `{env['image_id']}`. Docker inspect content size: **{env['image_size_bytes']:,} bytes** ({env['image_size_bytes']/2**20:.2f} MiB). Docker CLI reports **{disk_usage} disk usage**, separately recorded in `results-linux-amd64/image-size.txt`; content size is not unpacked disk usage.", '',
        'Runtime: Python 3.12.16, ONNX Runtime 1.32.0, NumPy 2.5.4, tokenizers 0.23.3, psutil 7.2.2. Exact Linux dependency versions: `results-linux-amd64/installed-requirements.txt`. No PyTorch/Transformers or ONNX exporter is installed in this runtime.', '',
        '| Case (batch / token cap / repeat) | Container peak MiB | Process peak RSS MiB | Load s | Warm median ms | Cgroup CPU (one core) | Exit / OOM |',
        '|---|---:|---:|---:|---:|---:|---|', *rows, '',
        'Load time covers local tokenizer + ONNX session initialization, excluding imports. Warm latency includes tokenization, ONNX forward pass, attention-mask mean pooling, L2 normalization and quota throttling. Raw files also contain imports, cold latency, all ten latency samples, current RSS, CPU/throttling counters and memory events. Container peak includes the cgroup-accounted cache; RSS includes mapped/shared pages and can be larger. Fresh containers do not flush shared filesystem caches. Background host workloads and emulation affect these results.', '',
        f"Largest measured container charge: **{max_peak:.1f} MiB**, leaving **{512-max_peak:.1f} MiB** below the limit in this model-only experiment. This subtraction is not a measured FastAPI budget.", '',
        '## Offline and failure checks', '',
        'All successful cases verify Docker network=none and cgroup limits; a real outbound TCP attempt is blocked by the OS with ENETUNREACH before inference. Python socket operations are guarded, inference network-attempt counts are zero, HF/Transformers offline flags are set, telemetry is disabled, and model/tokenizer hashes are verified before local loading. No hosted inference calls or runtime downloads occur.',
        'The read-only arbitrary-UID run may emit an ONNX Runtime warning that its import-time telemetry device ID could not be persisted; this is retained in stderr logs. Telemetry is then explicitly disabled before session creation, and the OS network namespace blocks any native outbound connectivity throughout.', '',
        '## Interpretation', '',
        ('512 MiB is sufficient for all tested **bounded model-only emulated runs**, without OOM. ' if complete else 'The full requested bounded experiment has not passed; inspect the failures before claiming memory fit. ') + 'Native Linux/amd64 throughput, AVX2 availability on CSC nodes, and combined application memory remain unverified.',
        'FastAPI, database access, PDF extraction, GitHub retrieval and overlapping HTTP requests were deliberately not loaded. There is no measured evidence that the remaining memory is sufficient for the complete application, and multiple model processes/concurrent calls are outside this test.',
        '**Recommendation:** keep the next model experiment in a separate internal model container with bounded sequential requests; validate it on native amd64 first. Do not integrate into the existing 512 MiB application container until a combined workload test demonstrates safe memory and CPU headroom. This recommendation does not add or deploy a service.', '',
        'Reproduction commands, resource enforcement and measurement definitions: [LINUX_AMD64.md](LINUX_AMD64.md). No application, database, matching, frontend, main Dockerfile or Kubernetes changes; no deployment, commit or push.',
        '', '## Validation commands', '',
        '- `python3 experiments/local_model/prepare_amd64.py`: artifact hashes/lengths verified (exit 0).',
        '- `docker build --platform linux/amd64 -f experiments/local_model/Dockerfile.amd64 -t recruitifi:minilm-amd64-int8 experiments/local_model`: PASS (exit 0).',
        f"- `python3 experiments/local_model/run_amd64.py --repeats 2`: {'PASS (exit 0)' if complete else 'NOT a complete pass; inspect per-case states'}. Exact individual Docker commands and container exit codes are in each JSON.",
        '- `python3 -m py_compile experiments/local_model/benchmark_amd64.py experiments/local_model/run_amd64.py experiments/local_model/summarize_amd64.py experiments/local_model/prepare_amd64.py`: PASS (exit 0).',
        '- `git check-ignore experiments/local_model/models/all-MiniLM-L6-v2/onnx/model_quint8_avx2.onnx experiments/local_model/.venv/bin/python`: both ignored (exit 0).',
    ]
    if measured:
        lines += ['', '## Synthetic similarity sanity check', '',
                  'Evidence: “Developed REST APIs using Python and FastAPI.” Compared with “Python and FastAPI REST API development.” and unrelated “Food hygiene and restaurant kitchen cleaning.”',
                  f"Matching cosine range: {min(m['similarities']['matching_python'] for m in measured):.6f}–{max(m['similarities']['matching_python'] for m in measured):.6f}; unrelated range: {min(m['similarities']['unrelated_kitchen'] for m in measured):.6f}–{max(m['similarities']['unrelated_kitchen'] for m in measured):.6f}. Every successful run asserts matching > unrelated. This is a sanity check, not a recruitment score or evaluation dataset."]
    (ROOT / 'RESULTS_LINUX_AMD64.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
