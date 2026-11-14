# Operator-only synthetic evidence analysis API

These controls are **disabled by default**. They do not provide real-candidate
authentication or authorize real personal data. Use only an isolated database of
synthetic candidates/materials. Nothing enables this feature on Rahti, changes the
frontend, or launches/downloads a model service automatically.

## Explicit enablement

Trusted server configuration must supply all of:

```text
TALENTMATCH_AI_SYNTHETIC_DEMO=1
TALENTMATCH_AI_SYNTHETIC_CANDIDATES=402,406
TALENTMATCH_AI_DEMO_TOKEN=<operator secret, 32–256 printable non-whitespace ASCII characters>
TALENTMATCH_EMBED_URL=http://127.0.0.1:18081/embed
```

The candidate list is mandatory, at most 15 positive IDs, comma-separated without
spaces. This is an **operator assertion that these profiles/materials are
synthetic**, not a PII detector. Do not enable it on a mixed/live database or a
public shared database receiving real uploads. Do not put the operator token in
JavaScript, URLs, files committed to Git, or logs. Generate/store it securely.

Every new endpoint requires `X-Recruitifi-AI-Token: <operator secret>` with a
constant-time comparison. Missing/wrong/ambiguous token → `403`. Disabled feature
→ `404`; missing/invalid enabled configuration → `503`; non-allowlisted candidate
→ `403`. The mock `X-Recruitifi-Demo-Account` header is **not authentication**:
it cannot replace the token. When supplied, its existing owner checks also apply.
Omitting it does not bypass the operator token or synthetic allowlist.

Existing hosted HTTP Basic protection is preserved. If enabled, supply its
credentials separately alongside the new operator header. CORS has not been
expanded to expose operator controls to the frontend. Use a trusted operator
client over loopback/HTTPS. There is no new user login system.

## Endpoints

All paths are under `/api/candidates/{candidate_id}`:

| Method | Path | Behavior |
|---|---|---|
| POST | `/materials/{material_id}/analysis` | Admit one job; return `202`, job ID, relative status/result URLs. |
| GET | `/analysis-jobs/{job_id}` | Read scoped persisted job status and sanitized error code. |
| GET | `/analysis-jobs/{job_id}/result` | Read job and persisted analysis with sources/findings. Active jobs return `202`; completed/failed jobs return `200`, with analysis null if no run exists. |
| GET | `/materials/{material_id}/analyses` | Last 50 jobs and bounded analysis-run history for that material. |
| DELETE | `/analysis-jobs/{job_id}` | Delete a terminal job and its associated run/sources/findings, not the material. Active jobs return `409`. |

Trigger body is optional (default top-k 3), or:

```json
{"top_k": 3}
```

Only an integer 1–5 is accepted. Extra fields, including URLs, model endpoints or
submitted evidence text, are rejected. Body size is at most 512 bytes. Candidate/
material IDs must fit positive SQLite integers; job IDs are server-generated
32-character hex UUIDs. All feature responses have `Cache-Control: no-store`.
Unknown/wrong-candidate jobs/materials return `404`. Deleted source results return
`410` once their job terminates. Poll conservatively (e.g. once per second).

Project links compare only saved descriptions/titles, without URL fetching. Project
uploads must be PDFs with matching filename/MIME metadata and at most 10 MiB;
the existing extractor retains its 10-page/20,000-character/no-OCR limits and
clear extraction statuses. GitHub records must contain a supported repository
URL; profile/branch/file/arbitrary URLs are rejected before admission. Triggering
a GitHub job explicitly requests the existing anonymous fixed-host GitHub API
retrieval; it never clones, executes source, installs dependencies or follows links.

## Processing and lifecycle

The request only validates/adopts IDs/options and commits a `queued` job. The
actual extraction, retrieval and inference run in a **spawned worker process**,
supervised by a single-thread background executor. HTTP sync handlers run in
FastAPI's thread pool; neither inference nor SQLite work blocks the event loop.

The additive `evidence_analysis_jobs` table stores only operational IDs/options,
status, lease, timestamps and a result-run reference. A partial unique SQLite
index allows **one queued/running job globally across application workers**;
another index enforces candidate admission. There is no unbounded queue. Busy
admission returns `429` plus `Retry-After: 1`. A transient unavailable supervisor
returns `503` and marks its admitted job failed.

Each job has an absolute **150-second deadline**, including extraction and process
startup. Existing GitHub/model pipeline budgets remain tighter. The parent
supervisor terminates/kills timed-out/cancelled children. The child also has a
POSIX absolute-deadline alarm so an orphan cannot continue indefinitely after an
API worker crash. Leases expire only after that deadline plus a ten-second grace;
subsequent authenticated requests mark stale jobs `interrupted`. These are not
real-time OS scheduling guarantees. POSIX Linux/macOS process support is required.

Statuses: `queued`, `running`, `completed`, `failed`, `timed_out`, `cancelled`,
`interrupted`. No fake findings are produced on failure. A partial/failed pipeline
report can retain valid diagnostic/deterministic results in storage while its
job is marked failed (`analysis_incomplete`); inspect the analysis's own status
and stage/error fields, not just the existence of a run.

Results are transferred as bounded JSON (at most 1 MiB), never arbitrary pickled
repository data. Persistence uses the existing storage module, validating IDs,
ownership, sources, bounded excerpts, model version and **unreviewed** findings.
Candidate skills, compatibility scores, jobs, swipes and notifications are not
modified. Only job metadata and explicit AI analysis tables are written.

Material deletion cascades existing saved analysis; the job's material/run keys
become null, retaining its active global admission until the supervisor stops it.
Deleted/changed ownership or disabled synthetic configuration cannot publish a
stale result. Shutdown signals cancellation and reaps workers outside the event
loop. The endpoint does not offer force-cancelling active jobs; wait for completion
or use normal application shutdown/source deletion. Deleting finished results
does not delete candidates or original uploaded documents.

## Security limits and next gates

The existing embedding client still permits **loopback only**, ignores proxies,
rejects redirects and verifies pinned model/revision/finite normalized vectors.
No internal-cluster hostname exceptions or external AI providers are added.
The local model must already be available on its approved loopback port. The
model service's missing caller authentication remains a blocker for broader
networking or real-data use.

Workers suppress input-bearing parser logs/stdout/stderr. API error responses/job
records contain fixed sanitized codes, never exception strings, documents, raw
repositories, embeddings or credentials. Results intentionally include authorized
short evidence excerpts and source references; treat them as untrusted text.

Operator-token/allowlist protection is for this controlled synthetic phase, not
per-user production identity or permission management. Before any real candidate
or public UI integration, implement genuine owner authorization, model-service
authentication, privacy/consent and egress controls, evaluate semantic quality,
and measure combined process memory/CPU on native Linux. Process timeouts do not
impose a separate memory cgroup on a hostile PDF; the parser still requires
resource/isolation evaluation before untrusted real uploads are analyzed.

## Validation

```sh
backend/.venv/bin/python -m unittest backend.test_evidence_api -v
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py'
```

Mocked API tests use disposable databases, mocked model/GitHub responses and
controlled background workers; no real documents or live network are used. They
cover gates/token/role spoofing, owner scoping, asynchronous admission, global DB
limits, PDF/GitHub dispatch, bounded input, unavailable models, elapsed deadlines,
shutdown/deletion, rollback-safe persistence, unchanged application data and log
privacy. Supervisor tests also cover hard termination/orphan alarms and one real
spawn round trip on empty synthetic evidence (no model call).

Local validation: **19 focused API/supervisor tests and all 195 backend tests
passed** (exit 0). Python compilation and diff whitespace validation also passed.
No live SQLite, real candidate materials, hosted inference or deployment was used.
