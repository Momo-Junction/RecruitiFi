# Step 4C verification results

**PASS locally; native Linux/amd64 and CSC Rahti execution remain NOT TESTED.**

All changes for Step 4C are contained under `experiments/local_model/service/`.
No application, frontend, database, scoring, main Dockerfile, or Kubernetes files
were changed. No deployment, commit, push or public port publication occurred.

## Commands and results

Run from the repository root unless a directory is specified:

| Check | Command | Result |
|---|---|---|
| Native Mac tests | `cd experiments/local_model && .venv/bin/python -m unittest service.test_service -v` | 18 tests PASS, exit 0 |
| Python syntax | `cd experiments/local_model && .venv/bin/python -m compileall -q service` | PASS, exit 0 |
| Image build | `docker build --platform linux/amd64 -f experiments/local_model/service/Dockerfile -t recruitifi:minilm-service experiments/local_model` | PASS, exit 0 |
| Container suite + HTTP | `python3 experiments/local_model/service/run_container_checks.py` | PASS, exit 0 |
| Ignored artifacts | `git check-ignore experiments/local_model/models/all-MiniLM-L6-v2/onnx/model_quint8_avx2.onnx experiments/local_model/service/__pycache__/app.cpython-312.pyc` | Both ignored, exit 0 |
| Diff whitespace | `git diff --check` | PASS, exit 0 |

The container suite ran the same 18 tests successfully. Coverage includes true
ONNX vector dimensions, normalization, synthetic semantic sanity, exact 256-token
acceptance, 257-token rejection before model execution, mixed-batch token
rejection, empty/type/batch/body/character/Unicode/JSON validation, single startup
load, health/readiness, missing/tampered files, offline model loading/inference,
queue timeout/immediate overload, serialized execution, client cancellation, and
sanitized logging even when an inference exception contains a synthetic marker.

The missing-model container deliberately exited **3** with
`Local model initialization failed`; this is an expected rejection, not a failed
check. The normal server exited 0 after graceful Docker stop;
all experimental containers were removed.

A native Mac HTTP smoke check also passed health, readiness, embeddings and log
privacy on `127.0.0.1:18081`. Port 8080 was already occupied; its existing listener
was left untouched. The temporary process logged complete graceful shutdown,
then returned -15 because it was intentionally terminated with SIGTERM. Exact
command/status metadata is in `results/local-http.json`. It is not a Linux result.

## Architecture, image and model

Image architecture: **Linux/amd64**, runtime reports x86_64. Docker daemon:
**linux/aarch64** on macOS arm64, so **all Linux timings below use
x86 emulation**. They do not predict native CSC CPU performance.

Image: `sha256:3fe7614f7023efaa43db7a22f59100ece6e6d4017c0f01d6665761e71c2a4181`; Docker reports 516 MB disk usage and
132,406,041 bytes of content (different size measures).
Runtime: Python 3.12.16, FastAPI 0.162.7, Uvicorn 0.54.0, Starlette 1.10.0,
ONNX Runtime 1.32.0, NumPy 2.5.4, tokenizers 0.23.3. Full versions are in
`results/installed-requirements.txt`.

Model: `sentence-transformers/all-MiniLM-L6-v2`, revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Uses the benchmark's published x86 AVX2
`onnx/model_quint8_avx2.onnx` (dynamic UINT8), 23,046,789 bytes; with tokenizer,
23,513,036 bytes. The existing `../amd64_model_manifest.json` records SHA-256
hashes, checked before startup loading. No ARM artifact, remote model resolution,
AI-provider calls or runtime downloads.

## Actual container measurements

The real HTTP server ran once with 512 MiB memory, no swap, 0.5 CPU,
`--network=none`, read-only rootfs, `/tmp` tmpfs, no added capabilities and
arbitrary UID **1000620000**. Docker and cgroup limits were verified. Both
ONNX thread pools are one, CPU provider only. No ports were published; socket
inspection confirmed binding only to 127.0.0.1:8080.

- Peak container charge: **319.64 MiB**.
- Server current and high-water RSS: **306.43 MiB**.
- OOM kills, memory-limit events: **zero**.
- Observed startup to listening: **20.15 seconds**, including
  Python imports, local model load and runner polling; not isolated model load time.

The container peak includes the temporary `docker exec` HTTP test client as well
as the server. RSS includes shared/mapped pages and is a separate measurement
from cgroup charge. Shared filesystem caches were not flushed.

Three sequential HTTP requests were measured per case. Timings include JSON
transport, tokenization, inference, pooling, normalization, response serialization
and CPU throttling. Long cases actually contain exactly 256 tokens including
special tokens; short cases use a synthetic Python/FastAPI description.

| Batch | Tokens | Median HTTP latency ms |
|---:|---|---:|
| 1 | short | 1002.4 |
| 1 | 256 | 5724.4 |
| 3 | short | 1407.5 |
| 3 | 256 | 15492.3 |

The real busy-service check returned `429` for the waiting request, while
`/healthz` returned `200` during active inference. **The configured queue timeout
is two seconds, but measured HTTP response time was 4.33 seconds under
emulation/throttling.** Event-loop scheduling and transport can delay delivery
past the nominal timeout; this is not a strict end-to-end two-second SLA. Native
amd64 latency and overload response deadlines require further verification.

## Offline and privacy verification

The OS rejected an outbound TCP connection with errno **101 (ENETUNREACH)**.
Model loading/inference also passed Python socket guards. Runtime flags disable
HF downloads/telemetry and OpenTelemetry exporters; ONNX telemetry is explicitly
disabled before session creation. Real inference loaded only hash-verified local
files while Docker denied external networking.

Submitted marker text, the synthetic description and embeddings did not appear
in server logs. Neither the service nor the test measurements persist requests
or vectors. There were no inference failures. The read-only container emitted
ONNX Runtime's harmless import-time telemetry-device-ID persistence warning;
this contains no submitted text and external connectivity remains denied.

## Limits before integration

This establishes a bounded **standalone service** fit in the tested emulated
512 MiB container. It does not establish native Rahti performance, combined
RecruitiFi resource use, evidence-analysis quality, or production readiness.
Keep the service separate until native amd64 and end-to-end workload tests pass.
Before connecting RecruitiFi, require authorized internal-only access and denied
internet egress; this experiment deliberately has no caller authentication or
public networking. Keep one worker, bounded callers and overload-aware retries.
See [README.md](README.md) for the API and reproducible commands.
