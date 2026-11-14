# MiniLM local CPU benchmark results

Measured: 2026-11-14T13:58:22.300583+00:00

Host: Apple M1, arm64, 8 logical CPUs, 16.0 GiB RAM; macOS-26.6.2-arm64-arm-64bit.

Model: `sentence-transformers/all-MiniLM-L6-v2`; revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; license `apache-2.0`.

## Local model artifacts

| Artifact | Bytes | MiB |
| --- | ---: | ---: |
| model.safetensors | 90,868,376 | 86.66 |
| onnx/model.onnx | 90,405,214 | 86.22 |
| onnx/model_qint8_arm64.onnx | 23,026,053 | 21.96 |
| Shared tokenizer/config/card files | 710,039 | 0.68 |
| Total selected download | 205,009,682 | 195.51 |

Weights/caches/virtualenvs are ignored by Git. SHA-256 hashes are in model_manifest.json.

## Versions and startup

| Package | Version |
| --- | --- |
| torch | 2.15.0 |
| transformers | 5.23.0 |
| onnxruntime | 1.32.0 |
| tokenizers | 0.23.3 |
| numpy | 2.5.4 |
| psutil | 7.2.2 |
| safetensors | 0.8.0 |
| huggingface-hub | 2.4.0 |

Python: 3.12.14 (main, Aug 12 2026, 13:57:54) [Clang 21.0.0 (clang-2100.1.1.101)]

| Runtime | Import s | Model load s | Startup ready s | First 7-text inference ms | Peak process MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| PyTorch FP32 | 15.040 | 5.533 | 20.573 | 99.97 | 607.3 |
| ONNX FP32 | 1.223 | 0.096 | 1.319 | 27.53 | 592.8 |
| ONNX INT8 ARM64 | 0.082 | 0.067 | 0.148 | 11.26 | 590.1 |

Peaks are OS high-water RSS for a fresh process, including imports, load, warmup and all measured batches. They are not merely model weight sizes. Model disk caches were warm; no cold-disk claim.

## Warm end-to-end inference

One inference thread, CPU only; tokenization + model forward + mean pooling + L2 normalization. Values are median / p95 milliseconds.

| Profile | Batch | Padded tokens | PyTorch FP32 ms | ONNX FP32 ms | ONNX INT8 ARM64 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| short | 1 | 13 | 4.29 / 4.75 | 4.53 / 5.04 | 1.83 / 2.33 |
| short | 3 | 13 | 5.60 / 5.72 | 12.05 / 16.93 | 4.87 / 5.41 |
| short | 16 | 13 | 14.40 / 24.60 | 56.62 / 69.61 | 23.14 / 25.45 |
| short | 32 | 13 | 25.15 / 25.43 | 112.55 / 115.91 | 45.71 / 46.81 |
| max_256_tokens | 1 | 256 | 22.02 / 22.30 | 79.52 / 89.63 | 36.72 / 54.22 |
| max_256_tokens | 3 | 256 | 60.75 / 61.89 | 240.57 / 251.46 | 107.45 / 109.10 |
| max_256_tokens | 16 | 256 | 322.56 / 347.27 | 1365.95 / 1503.86 | 584.70 / 622.22 |
| max_256_tokens | 32 | 256 | 631.31 / 741.10 | 2890.15 / 3053.12 | 1194.00 / 1224.85 |

| Runtime | Measured CPU % of one core (range) | Max current RSS MiB |
| --- | ---: | ---: |
| PyTorch FP32 | 98.2–99.9 | 453.6 |
| ONNX FP32 | 97.6–100.3 | 424.1 |
| ONNX INT8 ARM64 | 95.8–99.9 | 579.3 |

100% CPU means one whole core. These runs do not enforce a 500m CPU quota.

## Synthetic similarities

Columns: Python/FastAPI, React/TypeScript, Docker/deployment, food hygiene/kitchen cleaning. Rows are the three requested synthetic project descriptions.

### PyTorch FP32

| Description | Python | React | Docker | Kitchen |
| --- | ---: | ---: | ---: | ---: |
| REST APIs/Python/FastAPI | 0.9509 | 0.2122 | 0.1027 | 0.1071 |
| React/TypeScript interfaces | 0.1467 | 0.7819 | 0.0302 | 0.0490 |
| Docker container configuration | 0.0720 | 0.0903 | 0.7764 | 0.0030 |

Maximum cosine delta from PyTorch: 0.00000000; highest-scoring requirement indices: [0, 1, 2].

### ONNX FP32

| Description | Python | React | Docker | Kitchen |
| --- | ---: | ---: | ---: | ---: |
| REST APIs/Python/FastAPI | 0.9509 | 0.2122 | 0.1027 | 0.1071 |
| React/TypeScript interfaces | 0.1467 | 0.7819 | 0.0302 | 0.0490 |
| Docker container configuration | 0.0720 | 0.0903 | 0.7764 | 0.0030 |

Maximum cosine delta from PyTorch: 0.00000018; highest-scoring requirement indices: [0, 1, 2].

### ONNX INT8 ARM64

| Description | Python | React | Docker | Kitchen |
| --- | ---: | ---: | ---: | ---: |
| REST APIs/Python/FastAPI | 0.9472 | 0.2037 | 0.0762 | 0.1162 |
| React/TypeScript interfaces | 0.1558 | 0.7893 | 0.0347 | 0.0681 |
| Docker container configuration | 0.0802 | 0.1026 | 0.7695 | -0.0009 |

Maximum cosine delta from PyTorch: 0.02656239; highest-scoring requirement indices: [0, 1, 2].

## Fresh processes with batches capped at 3

| Runtime | Peak MiB (only batches 1/3) | Short batch 3 median ms | 256-token batch 3 median ms |
| --- | ---: | ---: | ---: |
| PyTorch FP32 | 395.1 | 5.34 | 60.52 |
| ONNX FP32 | 226.0 | 11.98 | 239.01 |
| ONNX INT8 ARM64 | 155.7 | 4.93 | 106.91 |

These are separate, fresh network-blocked processes. The first seven-text similarity check is included in startup, followed only by batch sizes 1 and 3. All completed offline with zero inference-time Python network attempts. Lower bounded-workload peaks do not include FastAPI or concurrent analysis/extraction.

## Offline verification

Every runtime completed under macOS sandbox-exec with `(deny network*)`. Each first confirmed an outbound connect fails with EPERM/EACCES, then installed/tested Python socket guards before runtime import/loading. HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 were set; models were loaded from local files only. ONNX telemetry was disabled.
- PyTorch FP32: OS block errno 1; inference-time Python network attempts 0.
- ONNX FP32: OS block errno 1; inference-time Python network attempts 0.
- ONNX INT8 ARM64: OS block errno 1; inference-time Python network attempts 0.

No synthetic text was sent to hosted inference. Only package/model downloads used the network, before measurement.

## Rahti feasibility and limits

Reference deployment: one replica, 500m CPU limit, 512 MiB memory limit. The application and its retrieval/extraction allocations are NOT included in these isolated model-process measurements.
- PyTorch FP32: 607.3 MiB peak — EXCEEDS the 512 MiB limit even in isolation for the full stress workload.
- ONNX FP32: 592.8 MiB peak — EXCEEDS the 512 MiB limit even in isolation for the full stress workload.
- ONNX INT8 ARM64: 590.1 MiB peak — EXCEEDS the 512 MiB limit even in isolation for the full stress workload.

These Mac arm64 numbers are not Linux/amd64 cgroup results. A 500m quota provides half a core of sustained capacity on the same CPU; per-request latency need not scale linearly because of quota periods and bursts. No Linux/Rahti inference, CPU throttling, combined FastAPI process, cold filesystem-cache run, concurrency test, or production deployment was performed.

Recommended next experiment: ONNX Runtime CPU, prioritizing INT8 for bounded-workload memory headroom, with bounded batches/concurrency, testing FP32 and an x86-targeted INT8 artifact on Linux/amd64 under actual 500m/512 MiB limits. ARM64 INT8 measurements do not certify AVX2 performance or parity. Treat 512 MiB as unverified until that combined workload test passes with headroom; do not infer fitness from small weight files alone.

These are semantic similarity examples, not calibrated skill scores or proof of candidate expertise. Nothing changes RecruitiFi matching/scoring or evidence tiers.

See README.md for reproduction, requirements.lock for exact dependencies, and results/*.json for raw measurements.
