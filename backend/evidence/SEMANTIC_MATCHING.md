# Synthetic-only project evidence semantic relevance

This is an isolated backend library, not an application feature or API route.
It does not import the candidate matching engine, change compatibility scores,
update candidate skills, make hiring recommendations, or write analysis to SQLite.
No new dependencies, schema, frontend, Docker or Rahti changes are required.

GitHub integration reuses `match_evidence_fragments(...)`, the shared comparison
function factored from the project wrapper. It accepts at most six attributed
fragments and an optional absolute monotonic `deadline` that can only shorten the
120-second comparison cap. Existing project output and cosine calculations are
preserved. See [GITHUB_PIPELINE.md](GITHUB_PIPELINE.md).

## Entry points and data

`semantic_matching.match_project_material(record, *, connection,
synthetic_data=False, top_k=3)` calls the existing `extract_project_material` on
a supplied stored-material-shaped record. Alternatively,
`match_project_evidence(extractor_output, ...)` accepts existing `ProjectEvidence`
data. Both require the explicit `synthetic_data=True` declaration. This is a
caller declaration, not a PII detector or an authorization mechanism.

The caller owns the **isolated synthetic SQLite connection**; the matcher never
opens the default/application database. Use the existing `database.connect()`
against a disposable test database, as the manual test demonstrates. It issues
only `PRAGMA table_info(skills)` and a bounded `SELECT`; no commits, updates or
schema changes. Tests assert no writes, and the manual test enables query-only
mode before analysis. Candidate/material authorization remains future work.

Catalog IDs and names come directly from `skills`, including non-contiguous IDs.
The actual schema contains `id`, `esco_uri`, `name`, `category`, **no description**.
Names alone are embedded; categories/ESCO URIs are not invented descriptions or
fetched externally. If a caller's catalog already has a `description` column, its
stored nonblank description is appended to its name. This does not add a column.
Linked skill associations in materials do not boost or force any result.

Project title and description are compared as separate fields. PDF text is used
only for the extractor's `extracted`/`text_limit_reached` statuses. A malformed or
scanned PDF can still have metadata compared, explicitly attributed to that
metadata field; no PDF content is fabricated. Project links use only saved
metadata and retain `external_content_status: not_analyzed`. Nothing fetches
URLs or integrates the GitHub fetcher in this step.

The returned JSON-ready dictionary includes:

```text
material_id, model, revision, extraction_status, external_content_status,
coverage_limited, untrusted=true, status,
fragments: [
  {
    fragment_index, evidence_field, start, end,
    matches: [
      {
        skill_id, skill_name, similarity_score,
        material_id, evidence_source_type, evidence_field,
        supporting_excerpt, excerpt_start, excerpt_end,
        review_status: "unreviewed",
        interpretation: "semantic_relevance_only"
      }
    ]
  }
]
```

`start`/`end` are zero-based, end-exclusive character offsets into the original
extracted field for the embedded fragment. Excerpt offsets identify the exact
substring shown in `supporting_excerpt` (the fragment's first 160 characters).
There is no whitespace rewriting or generated explanation. An excerpt is source
attribution, **not a causal explanation or proof of competence**. All content is
untrusted data; no instructions in it are executed or followed.

Status is `complete`, `limited` when meaningful text exceeds coverage limits or
extraction was truncated, `no_evidence`, or `no_skills`. The latter two return no
scores and make no model requests. Service errors raise exceptions instead of
returning fabricated/partial success.

## Similarity and bounds

The service must return the pinned MiniLM model/revision, exactly one finite
384-dimensional vector per input, with unit norm within 0.001. Malformed counts,
booleans, nonnumeric/nonfinite values, zero/non-unit vectors, unexpected models
or revisions are rejected. Cosine is calculated using Python's `math.fsum`:

`sum(evidence[i] * skill[i]) / (norm(evidence) * norm(skill))`

Only roundoff is clamped to [-1, 1]. Results sort by descending cosine then
ascending stored skill ID for deterministic ties. Default top-k is 3, allowed
range 1–5, per fragment. No percentage conversion or suitability threshold is
introduced. Even unrelated evidence has a relative top-k: this is **semantic
relevance only**, not verified competence or a hiring recommendation.

- At most 100 catalog skills; oversize catalogs are rejected, not silently sampled.
- Skill comparison text: at most 400 characters; longer stored input is rejected.
- At most six nonblank evidence fragments of 200 characters, in title,
  description, then PDF order. Excess text is explicitly marked `coverage_limited`.
- Extracted fields are bounded to 20,000 characters, consistent with the PDF cap.
- Each `/embed` request contains at most three strings and 16,384 UTF-8 JSON bytes.
- Responses: at most 131,072 bytes, enforced during reads before JSON parsing.
  Only JSON and identity content encoding are accepted; compressed content,
  conflicting/duplicate headers, oversized lengths and malformed JSON are rejected.
- No tokenizer/model is installed in the backend. Character chunks are not an
  exact token budget for all Unicode text: the service's 256-token limit remains
  authoritative. A `422` aborts with `input_rejected`; no silent truncation/retry.
- One analysis and one HTTP request per process, fail-fast on contention. No
  automatic retries or unrestricted queues. Service-side bounds remain in force.
- Two-second connection timeout, 30-second idle read timeout, 35-second total
  request deadline, 120-second comparison budget. A watchdog shuts down the
  numeric socket even for slow headers/bodies; deadlines are also checked between
  batches. There are at most 36 embedding POSTs plus one readiness GET.

These deadlines are not real-time scheduling guarantees. PDF extraction retains
the existing parser limits and is not enclosed in a new process/CPU sandbox or
the comparison deadline. Fixed character windows can split words and lose
context; limited coverage must remain visible to future callers/UI.

## Connection policy and errors

Set the trusted process environment, never a request or evidence field:

```sh
TALENTMATCH_EMBED_URL=http://127.0.0.1:18081/embed
```

Only exact `http://127.0.0.1:PORT/embed`, `http://localhost:PORT/embed`, and
`http://[::1]:PORT/embed` are allowed (explicit port 1–65535). Localhost maps
directly to numeric 127.0.0.1; no DNS resolution occurs. Credentials, query,
fragment, encoded paths, public/private/link-local addresses, lookalike hosts,
alternate paths, and every non-loopback hostname/IP are rejected. **No internal
cluster destinations are approved in Step 5A.** HTTP is permitted only on loopback.

The client uses direct numeric sockets via `http.client`, which ignores HTTP
proxy environment variables. Redirects are errors, never followed. Readiness
must identify the pinned model/revision before any evidence POST. This checks
protocol compatibility, not caller/server authentication. Evidence and catalog
inputs are sent only as arrays of strings; IDs and records are not sent.

`EmbeddingServiceError.code` is sanitized: `unsafe_configuration`, `busy`,
`timeout`, `unavailable`, `overloaded`, `input_rejected`, `redirect_rejected`,
`model_not_ready`, `invalid_response`, `request_too_large`, `response_too_large`,
or other fixed protocol/input error codes. Remote error bodies and raw network
exceptions are not echoed or logged. SQLite failures and invalid caller/catalog
data propagate as errors. The module has no request, excerpt or vector logs.

## Reproduce tests

From repository root, no service/network required:

```sh
backend/.venv/bin/python -m unittest backend.test_semantic_matching -v
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py'
```

Optional **synthetic-only** integration, separate terminals:

```sh
# Terminal 1: existing experiment environment/artifacts; loopback, no access logs.
cd experiments/local_model
.venv/bin/python -c "import uvicorn; uvicorn.run('service.app:app', host='127.0.0.1', port=18081, workers=1, access_log=False, limit_concurrency=8)"
```

```sh
# Terminal 2, repository root:
TALENTMATCH_EMBED_URL=http://127.0.0.1:18081/embed \
  backend/.venv/bin/python -m backend.evidence.manual_semantic --synthetic
```

The manual test patches the existing connection's DB path to a temporary database,
copies only the existing skill catalog names/ID assignment from `seed_data.SKILLS`,
and uses an inline synthetic project record. It does not open the configured
application DB, load candidate documents or persist analysis. It prints a
synthetic report and deletes its disposable DB on exit. Stop the temporary model
server with Ctrl-C; do not disturb other existing listeners or expose a public port.

Validation for this step: **22 focused mocked tests and all 139 backend tests
passed** (exit 0). The optional real-model integration passed on native Mac arm64
using an unused loopback port and the pinned local artifact. Example observed
title-fragment results included stored FastAPI ID 4 (cosine 0.6395) and Python ID 1
(0.4910); these are synthetic relevance values, not skill ratings. Native
Linux/amd64 and CSC integration were not tested in this step.

## Before persistence or UI work

This is ready as an **experimental building block**, not a production integration.
The model service still lacks authentication. Do not send real materials, approve
cluster destinations or add application/API wiring until caller authorization,
model-service access control, privacy/consent and internal network isolation have
been reviewed. A malicious local service could spoof readiness; compatibility
checks are not an identity/security boundary. Process-local locks do not enforce
global limits across backend workers. Skill embeddings are recomputed on every
call; there is no durable cache or results store. Quality, multilingual coverage,
fragment selection and future persistence/versioning/review workflows need
evaluation before displaying these values to users. Existing matching scores and
candidate profiles remain completely separate.
