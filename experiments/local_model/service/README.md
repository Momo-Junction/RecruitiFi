# Isolated local MiniLM embedding service

This experiment has no RecruitiFi imports, database, evidence retrieval, ranking,
or frontend integration. Use synthetic text only. It defaults to **127.0.0.1:8080**,
requires server-side bearer authentication on `/embed`, and must not be exposed publicly.
See `deploy/rahti/ai/README.md` at the repository root for the internal deployment.

## API

| Endpoint | Behavior |
|---|---|
| `GET /healthz` | Liveness, `200 {"status":"ok"}`. |
| `GET /readyz` | `200` with status, model and revision when loaded; otherwise `503`. |
| `POST /embed` | JSON array of 1–3 non-empty strings; returns normalized 384-dimensional vectors. |

Example request (host process running on loopback):

```sh
curl --fail-with-body -sS http://127.0.0.1:8080/embed \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TALENTMATCH_EMBED_TOKEN" \
  --data '["Developed REST APIs using Python and FastAPI."]'
```

Response shape (the vector is abbreviated, not literal JSON):

```text
{
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
  "embeddings": [[384 normalized floating-point values]]
}
```

Vectors follow input order. No identifiers or input text are returned. Errors use
`{"error":{"code":"...","message":"..."}}` without echoing submitted text:

- `400`: malformed JSON or invalid UTF-8.
- `401`: missing, wrong or duplicate service bearer credentials.
- `415`: missing/unsupported content type; use `application/json`.
- `422`: wrong shape/type, empty/whitespace-only string, invalid Unicode, too many
  strings, or oversized text. Strings have an 8,192-character safety ceiling and
  **256-token maximum including special tokens**. Truncation is disabled; token
  limits are checked before model execution. No partial batch results.
- `413`: streamed JSON request body exceeds 32,768 bytes, before parsing.
- `429`: one inference is active and its single waiting slot is occupied, or a
  waiter cannot acquire inference within two seconds. Includes `Retry-After: 1`.
- `503`: model unavailable or inference failed. Uvicorn may also return `503`
  when its eight-connection/request concurrency limit is reached.

Success and structured error responses carry `Cache-Control: no-store`.

## Model and concurrency

The service reuses the benchmark's pinned `amd64_model_manifest.json`, tokenizer,
and `onnx/model_quint8_avx2.onnx` (dynamic UINT8, upstream AVX2 variant). It verifies
the model identity, revision, permitted filenames, sizes and SHA-256 hashes at
startup, then creates one local tokenizer and ONNX session. There is no remote
model identifier resolution, hub fallback, remote code, or runtime installation.
`LOCAL_MODEL_DIR` optionally selects another local directory containing the same
verified artifacts; it cannot select another model or revision.

Only `CPUExecutionProvider` is permitted; intra-op and inter-op threads are both
one. Pooling uses the attention mask followed by L2 normalization. Tokenization
and inference run off the event loop, under the same admission gate, so health
requests remain responsive. One active task and one waiter are allowed per
process. Client cancellation cannot free an active slot while native inference
continues. Shutdown drains admitted tasks. Native inference is not forcibly
interruptible; only queue waiting has a two-second deadline.

Model loading occurs once during FastAPI lifespan startup. Missing/corrupt files
fail startup clearly; there is no fake readiness or synthetic fallback. Uvicorn
does not begin listening until startup completes. Run **one worker**, without
reload, using the provided launcher; extra workers would each load a model and
multiply the process-local concurrency/memory limits.

## Run on the host

From the repository root, reuse the isolated experiment virtual environment:

```sh
# Online preparation only, before service startup:
python3 experiments/local_model/prepare_amd64.py
experiments/local_model/.venv/bin/python -m pip install --only-binary=:all: \
  -c experiments/local_model/requirements.lock \
  -r experiments/local_model/service/requirements.txt
cd experiments/local_model
.venv/bin/python -m unittest service.test_service -v
# Generate only a transient local synthetic-test secret; never print/share it.
export TALENTMATCH_EMBED_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
.venv/bin/python -m service
```

No backend dependencies are changed. The launcher binds only to loopback and
disables access logs. HF offline/telemetry flags are forced before ML imports;
ONNX telemetry and OpenTelemetry exporters are disabled. There are no request,
embedding, exception-detail, or candidate-evidence logs and no persistence.

## Constrained offline Docker validation

From the repository root:

```sh
docker build --platform linux/amd64 \
  -f experiments/local_model/service/Dockerfile \
  -t recruitifi:minilm-service experiments/local_model
python3 experiments/local_model/service/run_container_checks.py
```

The Dockerfile-specific ignore file allowlists the two model assets, manifest,
constraints and service code; no application data, other weights or virtualenv
enters the context. Python 3.12.16's amd64 base is digest-pinned. Production
dependencies are pinned by `requirements.txt` plus the existing experiment lock;
the exact installed Linux versions are recorded in the image and test results.
Focused test scripts are included for offline validation, not exposed as routes.

The runner sequentially creates uniquely named disposable containers with
`--memory=512m --memory-swap=512m --cpus=0.5 --network=none`, a read-only rootfs,
non-executable `/tmp` tmpfs, UID `1000620000:0`, dropped capabilities and no new
privileges. It runs the full tests, starts a fresh real HTTP server, measures
synthetic HTTP batches, checks logging, and checks missing-model startup rejection.
Only its own containers are removed. No ports are published.

The real client runs using `docker exec` inside the same loopback network
namespace. It verifies an outbound connection is rejected by the OS, validates
the actual cgroup quotas, and checks the server listens on 127.0.0.1 rather than
all interfaces. Socket guards also cover model load/inference in the unit tests.
Offline operation is not inferred solely from environment variables.

`results/container-checks.json` contains measurements and exact Docker commands,
exit/OOM states, resource settings, architecture and logging results. The peak
cgroup memory includes the temporary HTTP test client as well as the server;
server current/peak RSS is reported separately. Three HTTP measurements per
batch/token case include JSON transport and serialization. The real concurrency
smoke check allows a fast native inference to finish before the queue deadline;
deterministic unit tests verify immediate overload, timeout, serialization and
cancellation semantics independently of machine speed.

## Before connecting RecruitiFi

- Native Linux/amd64 performance and actual CSC execution remain unverified when
  Docker is running on Apple Silicon. Treat emulated timings accordingly.
- The image is readable by arbitrary OpenShift UIDs and requires no runtime root
  operations or source writes. It relies on the platform to assign its UID; local
  Docker tests explicitly supply one. No Kubernetes resources are added here.
- A future internal-container listener can explicitly opt in to `--host 0.0.0.0`.
  Before doing so, require internal-only service discovery, restricted authorized
  callers, denied internet egress, and appropriate HTTP timeouts/rate limits.
  Do not create a public Route, Ingress or unrestricted port publication.
- Caller bearer authentication is required; there is no persistent job queue.
  Callers must handle `429`/`503` and avoid unrestricted retries/concurrency.
- A read-only arbitrary-UID run may emit ONNX Runtime's import-time warning that
  a telemetry device ID cannot be persisted. No submitted text is in that warning;
  telemetry is disabled before session creation and Docker blocks external egress.
- No combined RecruitiFi workload, evidence-analysis quality, matching behavior,
  or production operational readiness is established by this service experiment.
