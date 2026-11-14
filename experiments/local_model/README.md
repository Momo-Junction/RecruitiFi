# Local MiniLM feasibility experiment

The subsequent isolated Linux/amd64 container experiment is documented in
[LINUX_AMD64.md](LINUX_AMD64.md), with actual measurements in
[RESULTS_LINUX_AMD64.md](RESULTS_LINUX_AMD64.md). The rest of this page describes
the original native Mac experiment.

Standalone experiment on `LocalLLM`, independent of FastAPI, evidence extraction,
matching, frontend, SQLite, Docker and Kubernetes. Only synthetic sentences are
used. There is no hosted inference call or integration with the application.

Model: `sentence-transformers/all-MiniLM-L6-v2`, pinned revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, Apache-2.0 according to the pinned model
metadata/card. `model_manifest.json` records selected artifact sizes and SHA-256
hashes. Only safetensors, model/tokenizer configuration, FP32 ONNX and ARM64 INT8
ONNX artifacts are downloaded; no pickle weights or remote Python code.

The machine's default Python 3.15 is deliberately not used. The isolated `.venv`
uses installed Python 3.12 and native Apple Silicon wheels. `requirements.txt`
contains direct dependency pins; `requirements.lock` records all resolved versions.
The sentence-transformers Python package is not needed: PyTorch/Transformers and
ONNX run the same model with attention-mask mean pooling and L2 normalization,
matching the downloaded pooling/normalization configuration. The ONNX benchmark
uses the lightweight tokenizer directly rather than importing PyTorch/Transformers.

## Reproduce on macOS

```sh
python3.12 -m venv experiments/local_model/.venv
experiments/local_model/.venv/bin/python -m pip install --only-binary=:all: -r experiments/local_model/requirements.lock
# Explicit online artifact-download phase; no synthetic inputs are transmitted:
experiments/local_model/.venv/bin/python experiments/local_model/download_model.py
# Offline phase: launcher applies the OS deny-network profile to every child:
experiments/local_model/.venv/bin/python experiments/local_model/run_benchmarks.py
```

`offline.sb` denies all network activity, including native extensions/child
processes. Each benchmark first confirms an outbound TCP operation fails with
EPERM/EACCES, then installs and tests Python socket guards before importing ML
runtimes. `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and disabled telemetry are
also set. Models/tokenizers load only from the explicit local model directory,
with remote code disabled. No Hugging Face cache fallback or HTTP inference is
required. A failed OS-denial probe or an inference-time Python network attempt
fails the benchmark. OS enforcement is stronger than those environment flags.

For the separate fresh-process small-batch runs:

```sh
for runtime in torch onnx onnx-int8; do
  sandbox-exec -f experiments/local_model/offline.sb \
    experiments/local_model/.venv/bin/python experiments/local_model/benchmark.py \
    --runtime "$runtime" --batch-sizes 1 3 \
    --output "experiments/local_model/results/$runtime-small.json"
done
experiments/local_model/.venv/bin/python experiments/local_model/summarize.py
```

The final seven-text synthetic similarity sanity check runs once during startup
in each process, including the small-batch runs. Warm timed batches then follow
the requested batch sizes.

## Measurements and interpretation

Each runtime starts in a fresh process with one inference thread and CPU only:
PyTorch `.to('cpu')`, or ONNX `CPUExecutionProvider` (no MPS/CoreML/CUDA). Warm
batches of sizes 1, 3, 16 and 32 are measured for short descriptions and synthetic
inputs reaching 256 tokens. Timings include tokenization, forward execution,
attention-mask mean pooling and normalization. Imports, local model loading and
first inference are reported separately. Cosine similarity uses normalized
384-dimensional embeddings. Results report median/p95 latency and process CPU
time divided by wall time; 100% means one fully utilized CPU core, not the whole Mac.

Peak RSS comes from the OS process high-water mark (`resource.getrusage`), with
Darwin's byte units handled explicitly; per-case current RSS is also sampled via
psutil. Peaks include runtime imports, model loading, warmup and all batch cases.
These are runtime-process measurements, not just weight-file sizes. Filesystem
caches are not flushed, so load times are not a cold-disk benchmark. Background
applications can affect timings, and repeat counts are limited.

Mac arm64 results do not establish Linux/amd64 Rahti performance or cgroup memory
usage. A single thread on the Mac is not a measured 500m CPU quota. CPU-bound
work at 500m has at most half a core's capacity, before serving/API contention;
linear timing extrapolation is only an estimate. The 512 MiB limit must cover
FastAPI, retrieval/extraction and all model concurrency too. Linux/cgroup tests
and workload-level memory headroom remain required; this experiment does not
claim production readiness or modify those limits.

The supplied ARM64 INT8 artifact is architecture-targeted. A later Linux/amd64
experiment should use an appropriate x86 artifact (for example AVX2), test the
actual CPU instructions and numerical similarity, and enforce the real CPU/memory
limits. Do not transfer Apple latency or ARM INT8 results directly to Rahti.

`results/` contains synthetic outputs and measurements suitable for review.
Models, virtual environments, downloads/caches and binary artifacts are ignored
by Git. Nothing is committed or deployed automatically. Semantic similarity is
not evidence verification, a validated skill score, or a matching threshold.
