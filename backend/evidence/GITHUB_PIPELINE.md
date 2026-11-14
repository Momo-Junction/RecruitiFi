# Synthetic GitHub evidence analysis pipeline

`github_pipeline.py` is an explicit-call backend library. It adds no endpoint,
upload hook, application wiring, schema, storage, dashboard, dependencies or
infrastructure. Existing candidate compatibility and matching code is untouched.
Only explicitly declared **synthetic data** may be used during this phase.

## Inputs

```python
from backend.evidence.github_pipeline import analyze_github_material, analyze_github_materials

# `row` is a synthetic dict/sqlite3.Row shaped like an existing profile_materials
# GitHub link. `connection` is a caller-owned isolated synthetic SQLite connection.
report = analyze_github_material(row, connection=connection, synthetic_data=True, top_k=3)
# Optional bounded batch: 1–3 distinct repositories/materials for one candidate.
report = analyze_github_materials(rows, connection=connection, synthetic_data=True)
```

Required material fields: positive integer `id`, `candidate_id`,
`category='github'`, string `title` (at most 120 characters), string `description`
(at most 1,500 characters), and a supported repository `url`. File content is
rejected. Inputs may be the public material rows already returned by the existing
profile-material implementation. No default/application database is opened.
Duplicate material/repository identities or mixed-candidate batches are rejected.

The existing GitHub URL validator is called before fetching; the fetcher
revalidates its returned identifier. Repository URLs only are supported, not
GitHub profile URLs, arbitrary sites, branches, files, query strings or fragments.
Unsupported existing links are rejected; no repository discovery is attempted.
`synthetic_data=True` is a caller declaration, not authorization or PII detection.

## Retrieval and deterministic extraction

The pipeline invokes `fetch_github_repositories()` **once for the whole batch**.
No HTTP, cloning, redirect, download-URL or GitHub API logic is reimplemented.
The existing fixed-host API, TLS/DNS checks, secret/binary exclusion, regular-file
selection and Git blob-hash verification remain in effect.

Selection is unchanged: README.md, package.json, requirements.txt, pyproject.toml,
Dockerfile, then selected `.py`, `.js`, `.ts`, `.tsx` files, with existing stable
path/depth tie-breaks. Original paths/case, verified blob SHAs, tree SHAs and
immutable API source references are preserved, not rewritten into branch URLs.
Filename classification is case-insensitive; catalog association is an exact
case-insensitive stored-name match. There are no invented IDs or broad aliases.

Deterministic observations are intentionally limited:

- `package.json`: literal dependency names from dependencies, devDependencies,
  optionalDependencies and peerDependencies, with JSON-pointer provenance.
  Duplicate keys or malformed declarations are reported. Scripts and dependency
  version/URL values are not executed, followed or used as semantic inputs.
- `requirements.txt`: a conservative subset of named declarations, optional
  extras and comparison lists, with line-number provenance. Includes, URLs, VCS
  references, markers and unsupported forms are skipped and counted explicitly.
- `pyproject.toml`: static PEP 621 `project.dependencies` using that same named
  subset, with array-index provenance. Poetry/dynamic dependency resolution is
  not implemented. TOML is parsed as data, never imported or executed.
- Source extensions: `.py` → Python, `.js` → JavaScript, `.ts`/`.tsx` → TypeScript
  for catalog-name association only. TSX does not imply React.
- Dockerfile: literal file presence, associated with Docker only if that stored
  skill exists. Neither syntax validity nor runnable containers are claimed.

Every observation has `evidence_kind='deterministic_observation'`,
`interpretation='observation_not_proficiency'`, source provenance and
`review_status='unreviewed'`. Its optional skill associations use only existing
SQLite IDs/names, with `basis='exact_catalog_name'` and **no numeric similarity**.
These are observations of declared names/file metadata, not installed dependency
verification, valid code, candidate proficiency, contribution or authorship.

## Semantic relevance and source attribution

Only README text and saved material description/title are semantically compared.
Raw source files (including their comments), package scripts and manifest bodies
are not sent to the model. README code blocks/comments remain part of its text;
all such content is untrusted and embedded instructions are inert data.

The pipeline reuses the shared `semantic_matching.match_evidence_fragments()`
function, factored from the existing project comparison. Cosine, catalog lookup,
model identity/vector checks, top-k behavior, sanitized errors and the existing
local-only `EmbeddingClient` are reused. Project comparison output and existing
RecruitiFi matching scores are preserved. The project/PDF extractor remains
unchanged: GitHub links are not disguised as project/PDF materials.

Windows are 200 characters, with at most six fragments **globally**. Sources are
visited round-robin (README files, saved description, saved title), then materials
are visited round-robin. This gives deterministic coverage rather than letting a
single long README consume the entire budget. Excess text is explicitly marked
`coverage_limited`. No generated summaries or competence thresholds are used.

Each semantic match contains existing skill ID/name, cosine similarity, exact
supporting excerpt and offsets, `review_status='unreviewed'`, and
`interpretation='semantic_relevance_only'`. A provenance dictionary on fragments
and matches preserves candidate/material IDs, validated repository identity,
file path, tree SHA, blob SHA, immutable `source_reference`, field and untrusted
status. Saved metadata has `origin='material_metadata'` and **null file/blob
references**; repository text has `origin='repository_file'`. Offsets are Unicode
character offsets into that saved field or fetched file text, end-exclusive.

The first 160 fragment characters are an attributed display excerpt, not a
causal explanation. Semantic scores are not verified technical observations,
percentages, candidate skill levels, suitability or hiring recommendations.

## Output

```text
{
  status: complete | limited | partial | failed,
  model, revision, coverage_limited, untrusted, review_status,
  semantic_status: not_run | complete | no_skills | failed,
  errors: [{stage, code, material_id?}],
  materials: [{
    candidate_id, material_id, repository, tree_sha,
    retrieval_status, http_status, skipped,
    files: [{path, blob_sha, source_reference, decoded_bytes, untrusted}],
    observations: [{kind, observed_value, source, skill_associations, ...}],
    semantic_fragments: [{evidence_field, start, end, source, matches, ...}],
    extraction_issues: [{path, code, count?}], review_status, untrusted
  }]
}
```

Full repository text and embeddings are not returned, stored or logged. Bounded
excerpts are returned deliberately as supporting evidence. No candidate/profile
or analysis records are changed. The caller must preserve distinctions between
observation type, semantic status, extraction issues and limited coverage.

Missing/private repositories, forbidden/rate-limited requests, inaccessible
blobs and malformed/truncated responses retain the fetcher's exact status.
Failed repositories do not produce observations or semantic results; other
successful materials can still be reported. A model failure clears all semantic
results for the batch and returns its sanitized error code, while retaining valid
deterministic observations. This yields `partial` or `failed`, never fake success.
Malformed manifests are reported without inventing dependencies. Invalid caller
input, catalog/SQLite errors and busy analysis admission raise errors.

## Shared budgets and connection policy

One absolute monotonic **120-second pipeline deadline** starts before catalog
loading and retrieval. The fetcher accepts it through an optional keyword; its
own **30-second cap is never extended**. The same remaining deadline reaches
every model batch and is checked during extraction/scoring. It is not reset at
the retrieval-to-inference boundary.

Existing global retrieval limits remain: three repositories, 20 file attempts,
20,000 decoded bytes/file, 100,000 total decoded bytes, 2,000 tree entries,
64,000/512,000/32,000-byte metadata/tree/blob responses, two million total API
bytes, 26 requests, no redirects/retries and five-second connection/read caps.
Socket watchdogs now interrupt stalled/trickling response I/O at the retrieval
deadline. DNS waiting is bounded by the connection budget, with at most one
outstanding fixed-host resolver worker; a timed-out OS lookup may finish later
but performs no HTTP/analysis and prevents additional resolver-worker buildup.

Additional pipeline caps: 48 observations total, 32 dependency declarations per
file, six semantic fragments total, top-k 1–5 (default 3). Catalog cap remains
100 skills. At most 36 embedding POSTs plus one readiness GET are possible,
including catalog embeddings. Existing three-text batch, request/response byte
bounds, two-second connect/30-second idle read/35-second request deadlines are
also constrained by the remaining pipeline budget. No automatic retries.

There is one pipeline per process, one shared semantic comparison per process
and one model HTTP request per process. These are process-local admission limits,
not cluster-wide rate controls or real-time CPU scheduling guarantees. Parsers
operate only on already bounded text; this is not a general code-audit sandbox.

`TALENTMATCH_EMBED_URL` remains trusted process configuration only. Material URLs
or repository content cannot configure it. Only explicit literal loopback HTTP
destinations are accepted; no cluster hostname/IP is approved. The client ignores
proxy variables and never follows redirects. Evidence goes only to the local
model; public GitHub retrieval remains the separate fixed-host fetch path.

## Validation and remaining gates

```sh
backend/.venv/bin/python -m unittest backend.test_github_pipeline -v
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py'
```

Tests use synthetic in-memory SQLite catalogs, mocked GitHub REST responses
through the real fetcher, and mocked model embeddings. DNS/sockets, execution
and arbitrary URL fetching are guarded; no running model or internet is needed.
They cover provenance, IDs, declarative parsing, no authorship/proficiency claims,
global limits, time budgets, DNS/header/body stalls, partial failures and logging.

Recorded local results: **19 focused tests PASS**, **158 total backend tests
PASS** (both exit 0). Python compilation and `git diff --check` also passed.
No live GitHub or running-model test was performed for this pipeline.

Ready for further **isolated development**, not real-candidate persistence or UI
wiring. The model service still lacks authentication. Caller authorization,
trusted public-repository selection, privacy/consent, service authentication,
internal networking/egress, secret-detection gaps, multilingual/semantic quality,
review workflows and persistence/versioning require separate evaluation. A small
file subset and character windows are not a complete repository audit. Public
availability, dependencies and extensions never establish candidate authorship
or skill. No live GitHub, real candidate data, deployment, commit or push is used
to validate this step.
