# Bounded Linux/amd64 ONNX INT8 experiment

This is a standalone model benchmark, not an application or deployment change.
Use only synthetic inputs. Do not run against Rahti or a candidate database.
Actual results and limitations are in [RESULTS_LINUX_AMD64.md](RESULTS_LINUX_AMD64.md).

Added here: `Dockerfile.amd64`, `.dockerignore`, `requirements-linux.txt`,
`amd64_model_manifest.json`, `prepare_amd64.py`, `benchmark_amd64.py`, `run_amd64.py`,
`summarize_amd64.py`, this guide, the results report and `results-linux-amd64/`.
The existing experiment README links to these results. Existing model download
helpers, dependency constraints and Git exclusions are reused. No backend
dependency or application deployment configuration changes belong to this step.

## Preparation (network permitted)

Run from the repository root with Docker Desktop/Engine and Python 3.12 available:

```sh
python3 experiments/local_model/prepare_amd64.py
docker build --platform linux/amd64 \
  -f experiments/local_model/Dockerfile.amd64 \
  -t recruitifi:minilm-amd64-int8 experiments/local_model
docker image inspect recruitifi:minilm-amd64-int8 \
  --format '{{.Os}}/{{.Architecture}} {{.Id}} {{.Size}}'
```

The preparation script reuses the earlier downloader, verifies the pinned revision
and SHA-256 hashes in `amd64_model_manifest.json`, and retrieves just the tokenizer
and upstream **x86 AVX2** ONNX artifact. It does not reuse ARM64 INT8 weights.
Model binaries remain ignored by Git. The allowlisted experimental Docker context
excludes the virtualenv, other weights, application files and local artifacts.
The Python 3.12.16 amd64 base is pinned by manifest digest. Only binary Python
wheels are installed at build time; exact installed versions are recorded inside
the image and every measurement. The earlier dependency lock supplies constraints.
No packages, weights or tokenizers are downloaded at runtime.

## Offline constrained execution

```sh
python3 experiments/local_model/run_amd64.py --repeats 2
python3 experiments/local_model/summarize_amd64.py
```

The runner creates only uniquely named experimental containers and removes them
after collecting logs and exit/OOM state. It runs sequentially: no concurrent
model requests, no service, no application imports. Each of the four combinations
(batch 1/3, maximum 128/256 tokens) starts in a fresh container twice. Each case
includes one cold inference and ten timed warm iterations over synthetic text
that reaches the token limit, plus a small synthetic evidence/skill comparison.
The CLI accepts only those batch/token bounds, and every encode call enforces them.
Both ONNX thread pools are limited to one and graph execution is sequential.

For one manually controlled case:

```sh
docker run --rm --platform linux/amd64 \
  --memory=512m --memory-swap=512m --cpus=0.5 --network=none \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --user 1000620000:0 --cap-drop=ALL --security-opt no-new-privileges \
  --pids-limit=64 recruitifi:minilm-amd64-int8 \
  python benchmark_amd64.py --batch-size 3 --max-tokens 256
```

`--memory-swap=512m` together with `--memory=512m` disables swap, so it cannot
conceal a memory-limit failure. The script verifies cgroup v2 `memory.max`,
`memory.swap.max` and `cpu.max`, and the runner checks Docker's actual resource and
network settings. It deliberately fails on a host without these measurable cgroup
v2 interfaces rather than claiming an unverified quota.

`--network=none` removes external connectivity. Before imports a real outbound
TCP attempt must fail with an OS network/permission error; a timeout does not
count as proof. Python socket guards then reject and count network operations,
HF offline flags are asserted, telemetry is disabled, and only explicit local
model/tokenizer paths are used. Native code is also constrained by Docker's
network namespace. A host with an already cached image needs no online inference.

## Measurements and boundaries

`results-linux-amd64/` records the image identity/size, host and daemon architecture,
per-case Docker command/limits/exit/OOM status, raw benchmark logs and summary JSON.
Each successful case records:

- Cgroup `memory.peak` (whole-container charge, including accounted file cache),
  `memory.current`, events and memory limit. A fresh container is not a cold-disk
  test: shared host caches are not flushed.
- Process current RSS and Linux `ru_maxrss` high-water RSS; process RSS and cgroup
  charge are distinct measurements and can differ substantially under emulation.
- Import time, local tokenizer/model session loading time, first inference time,
  and ten warm tokenization + inference + masked mean pooling + L2 normalization
  timings. Timing uses wall clock, including CPU throttling.
- Cgroup and process CPU time divided by warm inference wall time; 100% means one
  core. Cgroup usage/throttling counters are authoritative for the enforced quota.
- ONNX CPU provider, configured threads, exposed CPU features, dependency versions,
  token lengths, cosine scores and network denial evidence.

An OOM-killed process may not emit final memory metrics; the runner still records
the Docker OOM/exit state and marks the case failed. No peak is fabricated for a
failed case. Results from an arm64 Docker daemon running an amd64 image are
**emulated**, even if `uname`/Python reports x86_64 inside. Such timings do not
predict native CSC node performance. Neither this experiment nor a model-only
memory fit validates FastAPI/extraction overhead or concurrent requests.

The graph uses dynamic activation quantization with UINT8 weight tensors and
MatMulInteger operations, from the upstream `model_quint8_avx2.onnx` artifact.
Observed quantized scales include per-channel vectors and scalars; graph/opset
details and hashes are in the manifest. We did not reproduce upstream export or
calibration settings, which are not fully encoded in the graph. AVX2 capability
must be checked again on the actual target CPU. This is a feasibility/similarity
sanity test, not validation of any recruitment scoring or evidence verification.
