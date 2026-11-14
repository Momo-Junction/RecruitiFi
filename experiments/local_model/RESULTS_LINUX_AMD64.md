# Linux/amd64 INT8 feasibility results

Eight-case local experiment: **PASS**. Native Linux/amd64 / CSC validation: **NOT TESTED**.

Tested image: Linux/amd64; Python reports x86_64. Host: Darwin arm64; Docker daemon: linux/aarch64 (Engine 29.7.2).
**These measurements use x86 emulation on Apple Silicon, not native amd64 hardware.** Exposed AVX2 capability is recorded in each JSON. Do not extrapolate these wall times to CSC CPUs.

Every case has a fresh container: 512 MiB cgroup limit, no swap, 0.5 CPU, network none, read-only rootfs, arbitrary non-root UID 1000620000, one intra-op and one inter-op thread, CPU provider only. Cases run sequentially, twice each; ten warm iterations plus cold inference and a synthetic similarity check. Maximum token lengths are actually reached.

Model: `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, Apache-2.0. Upstream x86 `onnx/model_quint8_avx2.onnx`: **23,046,789 bytes (21.98 MiB)**; with tokenizer: 23,513,036 bytes (22.42 MiB).
Quantization: dynamic UINT8 activations/weights with MatMulInteger (48 nodes), opset 14; both vector/per-channel and scalar scales observed. This is the published AVX2 artifact, not an ARM artifact or local re-quantization. Exporter/calibration settings beyond what is observable in the graph are unverified. Hashes and graph details are in `amd64_model_manifest.json`.

Image ID: `sha256:7488e8c2efb5d7d088ea493f1f871ad0ba121524e140d8e1062dcc83ccf45664`. Docker inspect content size: **127,875,737 bytes** (121.95 MiB). Docker CLI reports **496MB disk usage**, separately recorded in `results-linux-amd64/image-size.txt`; content size is not unpacked disk usage.

Runtime: Python 3.12.16, ONNX Runtime 1.32.0, NumPy 2.5.4, tokenizers 0.23.3, psutil 7.2.2. Exact Linux dependency versions: `results-linux-amd64/installed-requirements.txt`. No PyTorch/Transformers or ONNX exporter is installed in this runtime.

| Case (batch / token cap / repeat) | Container peak MiB | Process peak RSS MiB | Load s | Warm median ms | Cgroup CPU (one core) | Exit / OOM |
|---|---:|---:|---:|---:|---:|---|
| b1-t128-r1 | 191.0 | 235.2 | 2.383 | 2258.8 | 50.0% | 0 / False |
| b1-t256-r1 | 201.6 | 244.3 | 2.610 | 4992.1 | 50.0% | 0 / False |
| b3-t128-r1 | 200.5 | 243.8 | 2.301 | 6685.7 | 50.0% | 0 / False |
| b3-t256-r1 | 250.1 | 294.1 | 2.298 | 14908.0 | 50.0% | 0 / False |
| b1-t128-r2 | 191.2 | 235.0 | 2.303 | 2280.2 | 50.0% | 0 / False |
| b1-t256-r2 | 202.8 | 244.9 | 2.317 | 4922.9 | 50.0% | 0 / False |
| b3-t128-r2 | 202.1 | 245.4 | 2.229 | 6740.2 | 50.0% | 0 / False |
| b3-t256-r2 | 243.2 | 285.2 | 2.285 | 14906.6 | 50.0% | 0 / False |

Load time covers local tokenizer + ONNX session initialization, excluding imports. Warm latency includes tokenization, ONNX forward pass, attention-mask mean pooling, L2 normalization and quota throttling. Raw files also contain imports, cold latency, all ten latency samples, current RSS, CPU/throttling counters and memory events. Container peak includes the cgroup-accounted cache; RSS includes mapped/shared pages and can be larger. Fresh containers do not flush shared filesystem caches. Background host workloads and emulation affect these results.

Largest measured container charge: **250.1 MiB**, leaving **261.9 MiB** below the limit in this model-only experiment. This subtraction is not a measured FastAPI budget.

## Offline and failure checks

All successful cases verify Docker network=none and cgroup limits; a real outbound TCP attempt is blocked by the OS with ENETUNREACH before inference. Python socket operations are guarded, inference network-attempt counts are zero, HF/Transformers offline flags are set, telemetry is disabled, and model/tokenizer hashes are verified before local loading. No hosted inference calls or runtime downloads occur.
The read-only arbitrary-UID run may emit an ONNX Runtime warning that its import-time telemetry device ID could not be persisted; this is retained in stderr logs. Telemetry is then explicitly disabled before session creation, and the OS network namespace blocks any native outbound connectivity throughout.

## Interpretation

512 MiB is sufficient for all tested **bounded model-only emulated runs**, without OOM. Native Linux/amd64 throughput, AVX2 availability on CSC nodes, and combined application memory remain unverified.
FastAPI, database access, PDF extraction, GitHub retrieval and overlapping HTTP requests were deliberately not loaded. There is no measured evidence that the remaining memory is sufficient for the complete application, and multiple model processes/concurrent calls are outside this test.
**Recommendation:** keep the next model experiment in a separate internal model container with bounded sequential requests; validate it on native amd64 first. Do not integrate into the existing 512 MiB application container until a combined workload test demonstrates safe memory and CPU headroom. This recommendation does not add or deploy a service.

Reproduction commands, resource enforcement and measurement definitions: [LINUX_AMD64.md](LINUX_AMD64.md). No application, database, matching, frontend, main Dockerfile or Kubernetes changes; no deployment, commit or push.

## Validation commands

- `python3 experiments/local_model/prepare_amd64.py`: artifact hashes/lengths verified (exit 0).
- `docker build --platform linux/amd64 -f experiments/local_model/Dockerfile.amd64 -t recruitifi:minilm-amd64-int8 experiments/local_model`: PASS (exit 0).
- `python3 experiments/local_model/run_amd64.py --repeats 2`: PASS (exit 0). Exact individual Docker commands and container exit codes are in each JSON.
- `python3 -m py_compile experiments/local_model/benchmark_amd64.py experiments/local_model/run_amd64.py experiments/local_model/summarize_amd64.py experiments/local_model/prepare_amd64.py`: PASS (exit 0).
- `git check-ignore experiments/local_model/models/all-MiniLM-L6-v2/onnx/model_quint8_avx2.onnx experiments/local_model/.venv/bin/python`: both ignored (exit 0).

## Synthetic similarity sanity check

Evidence: “Developed REST APIs using Python and FastAPI.” Compared with “Python and FastAPI REST API development.” and unrelated “Food hygiene and restaurant kitchen cleaning.”
Matching cosine range: 0.939735–0.941039; unrelated range: 0.111488–0.130369. Every successful run asserts matching > unrelated. This is a sanity check, not a recruitment score or evaluation dataset.
