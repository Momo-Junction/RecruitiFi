# Explicit SQLite evidence persistence

`storage.py` saves existing project and GitHub analysis reports. It does not run
analysis, contact a model/GitHub, change candidate skills, or add API/UI wiring.
The analysis modules retain their synthetic-only restrictions. This phase was
tested exclusively against disposable SQLite databases, never the live database.

## Additive migration

Three tables are appended to the existing `backend/schema.sql`:

- `evidence_analysis_runs`: source material, analysis kind/status, model identifier
  and revision, extraction/retrieval/semantic status, first applicable sanitized
  error code, coverage flag, review status and UTC creation/update timestamps.
- `evidence_sources`: material fields or immutable GitHub repository/blob/path
  references, exact excerpt offsets, excerpts up to 160 characters and timestamps.
- `evidence_skill_findings`: existing skill ID/name snapshot, source reference,
  semantic cosine **or** deterministic observation, review status and timestamps.

`CREATE TABLE/INDEX IF NOT EXISTS` is additive and idempotent. The existing
application startup already executes this schema, so no new migration framework
or startup hook is needed. No existing table is altered, rebuilt, reset or seeded.
**No live migration was executed by this change.** Do not run the demo seeder to
migrate an existing database; the seeder has different data-initialization duties.

The migration was tested repeatedly on a populated legacy schema containing
synthetic documents, candidate skills, swipes, notifications, jobs and audits.
Those records and document bytes remain identical.

## Operations

All functions require an explicit caller-owned connection. Use the existing
`backend.database.connect()` context manager with the intended authorized database;
the persistence module never opens the default/application DB on its own. The
schema must already be initialized. For current development, use a disposable
synthetic database, as `backend/test_evidence_storage.py` does.

```python
from backend.evidence.storage import (
    save_analysis, get_analysis, list_analysis_runs,
    replace_analysis, delete_analysis,
)

# `connection` is an initialized, caller-owned synthetic connection.
run_ids = save_analysis(candidate_id, pipeline_report, connection=connection)
saved = get_analysis(candidate_id, run_ids[0], connection=connection)
history = list_analysis_runs(candidate_id, material_id=material_id,
                             limit=50, connection=connection)
replace_analysis(candidate_id, run_ids[0], single_material_report,
                 connection=connection)
delete_analysis(candidate_id, run_ids[0], connection=connection)
```

- Save accepts `match_project_material`/`match_project_evidence` output or a
  `github_pipeline` report. A GitHub batch produces one run ID per material,
  atomically; candidate/material ownership and repository identity are checked.
- Retrieve returns normalized run metadata, source rows, and finding rows linked
  by source ID. Findings retain their stored skill-name snapshot and their
  interpretation (`semantic_relevance_only` or `observation_not_proficiency`).
  Excerpts are always untrusted data. This is not a copy of the raw pipeline JSON.
- List is candidate-scoped, optionally material-scoped, newest run ID first,
  with a 1–100 row limit (default 50). It returns metadata, not full finding lists.
- Replace concerns one existing, owned run and the same single material. It
  preserves run ID/creation time, updates its timestamp/model metadata, replaces
  its sources/findings atomically and resets review to `unreviewed`. Other runs
  remain intact. Saving again instead creates another historical run.
- Delete removes only the owned analysis and its dependent sources/findings,
  leaving the original material and candidate data untouched. Unknown/wrong-owner
  run/material lookups raise `LookupError` rather than exposing another owner.

Writes use savepoints inside a caller-owned transaction. An operation starts a
transaction if needed, but does not commit it: the `database.connect()` context
commits on success or rolls back on error, or an explicit caller can commit/roll
back. Failed batch saves/replacements restore the prior analysis, preserving
unrelated pending caller writes. Reads do not start a migration or invoke analysis.

## Deletion and integrity

The run's material foreign key has `ON DELETE CASCADE`; source/run and
finding/source/run keys cascade too. The existing material DELETE endpoint uses
`database.connect()`, which already enables `PRAGMA foreign_keys=ON`, so deleting
a source material removes **all** its analysis history, references and findings
without endpoint changes. Other materials' analyses are retained.

Every SQLite writer must keep foreign keys enabled. Persistence writes refuse a
connection with enforcement disabled. External tools that deliberately disable
foreign keys can bypass SQLite cascades and are outside this guarantee. Composite
foreign keys prevent a finding from pointing to another run's source. Deleting a
catalog skill also deletes its findings; no nonexistent skill IDs are retained.

## Limits and retained data

The adapter accepts the existing bounds: up to three materials, six semantic
fragments and 48 observations per report, and at most five associations per
fragment/observation. It validates IDs/names against the current catalog, rejects
nonfinite/out-of-range scores, overlong/misattributed excerpts and invalid GitHub
paths/blob references. Model ID/revision lengths and schema status values are
bounded. Failed stages cannot import contradictory semantic/file findings.

Only field/path/blob references and excerpts up to 160 characters are stored;
identical sources supporting multiple skills within a run are deduplicated.
Deterministic findings have a null similarity score and separate observation
kind/value fields. Source excerpts for these observations are empty; their
immutable file/location references provide provenance.

There is no full-document copy, repository body, embedding vector, arbitrary
report JSON or raw error-message column. Unmapped observations without a skill
association and full diagnostic lists are intentionally not persisted; runs
retain their status, limited-coverage flag and first applicable sanitized error
code. Original documents remain solely in `profile_materials`.

New imports must be `unreviewed`. Accepted/rejected review values are reserved in
the schema for future explicit human-review work; no review endpoint is added.
Even a reviewed finding does not alter candidate evidence tiers or matching.
Candidate scoping is not authentication: future API callers must authorize access
before calling these internal functions. Historical excerpt accuracy remains the
trusted analyzer's responsibility; the store verifies identity/format and saved
metadata excerpts but does not re-download GitHub or reparse document BLOBs.

## Tests

```sh
backend/.venv/bin/python -m unittest backend.test_evidence_storage -v
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py'
```

Tests use temporary on-disk databases through the existing connection utility,
synthetic materials and mocked inference/GitHub responses. They cover idempotent
legacy migration, persistence across reconnects, both report formats, review and
version metadata, atomic multi-material save/replace/rollback, owner isolation,
run/material cascading deletion, bounds and schema constraints, and unchanged
application records. No live database, network or running model is needed.
