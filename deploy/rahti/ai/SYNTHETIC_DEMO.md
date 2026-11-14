# New fictional AI subject — preparation only

The current hackathon UI uses the password-free, exact-fixture boundary in
[PUBLIC_DEMO.md](PUBLIC_DEMO.md). The password/session setup below remains for
protected workflows; it is not required by that public demo UI. That new path
rejects edited/extra materials rather than analyzing them.

Proposed subject: candidate **900001**, account **talent-ai-001**.
Employer: existing **employer-001**, company **1**. No company needs inserting.
Candidates 402 and 406 are not AI subjects and are absent from this allowlist.
No Rahti database or cluster resource was accessed/changed during preparation.

## Smallest additive setup

- `backend/demo_accounts.py` retains every existing account mapping. One additional
  alias maps to 900001 and appears in the directory only after that record exists.
  Existing session/password/cookie/CSRF authorization is reused unchanged.
- `backend/evidence/synthetic_demo.py:provision(connection)` explicitly inserts
  one fictional candidate and one project material in a transaction. It is never
  called at startup and has no default database path or automatic CLI execution.
- The new profile uses an obvious fictional name/anonymous marker, `.invalid`
  email, fabricated language metadata, **no CV and an empty candidate skill list**.
  It does not grant or modify any candidate skill or matching percentage.
- The project title/description are literal fabricated fixtures in that module:
  an imaginary Python/FastAPI API, React/TypeScript interface and Docker setup.
  No GitHub repository, real document, candidate portfolio or copied text is used.
- The existing material schema requires either a URL or BLOB. An inert
  `https://example.invalid/recruitifi-ai-demo/900001` placeholder satisfies it
  without adding a document. The existing project extractor analyzes only title/
  description, never fetches this URL, and marks external content not analyzed.

The helper uses only INSERTs. It refuses an occupied candidate ID or missing
company 1, rolls back on unique-marker/material failures, and never upserts,
replaces, updates, deletes or reseeds existing data. Re-running it refuses the
occupied ID rather than overwriting previous records. It requires the existing
schema and a connection without an active transaction. No migration is added.

## Prepared private configuration

The previously prepared local `recruitifi-ai-browser-demo` Secret manifest was
updated **outside Git**, with newly rotated independent random passwords,
operator token and signing secret. Credentials are not included in this document.
Its companion Deployment patch still uses only `secretKeyRef` entries.

```text
TALENTMATCH_AI_SYNTHETIC_DEMO=1
TALENTMATCH_AI_SYNTHETIC_CANDIDATES=900001
TALENTMATCH_AI_EMPLOYER_ACCESS={"1":[900001]}
TALENTMATCH_AI_DEMO_ACCOUNTS=<only talent-ai-001 and employer-001, distinct random passwords>
TALENTMATCH_AI_SESSION_SECRET=<new independent random signing secret>
TALENTMATCH_AI_DEMO_TOKEN=<new independent random operator token>
```

No existing candidate IDs appear in the analysis allowlist or Employer grants.
The model-service token remains separate and unchanged. The existing browser
Secret was **not created/updated in Kubernetes**. Do not print/base64-decode its
contents into logs or commit it; its local file is 0600 in a 0700 temporary folder.

## Validation performed locally

Disposable SQLite and mocked embeddings verify:

- Existing accounts retain their exact candidate/company mappings; the new alias
  is available only when its candidate is provisioned.
- Only one candidate/material is added. Other synthetic fixture candidates,
  materials, catalog, companies, swipes, notifications and match-audit rows remain
  byte-for-byte equivalent. Failure/duplicate provisioning leaves them unchanged.
- New Talent password login, CSRF-protected triggering, background job results
  and explicit Employer read access use the existing authorization paths.
- Candidate 402, 406 and unrelated-subject analysis requests return 403 before
  processing. No analysis is performed on them by these new tests.
- Wrong-company, missing-grant and Employer-trigger requests are rejected.
- Results stay unreviewed and the new candidate skill list stays empty.

Run the focused tests with:

```sh
backend/.venv/bin/python -m unittest backend.test_synthetic_ai_demo -v
```

These are controlled tests; they do not prove live database contents, cluster
isolation or model availability. Existing regression suites use their own
disposable fixtures; no live applicant database is used.

## Blockers / future operator-only steps

1. Candidate ID 900001 and its unique anonymous/email markers must be checked for
   availability in the target database. Live availability is unverified. Do not
   repoint an existing account or overwrite a collision; stop and choose/review
   another explicit new identity if occupied.
2. Existing company 1 must be present. Do not seed/reset existing data to create it.
3. A reviewed application image containing the additive alias/helper is required.
   It has not been deployed. Provisioning requires separate explicit execution
   authorization, a SQLite-safe backup and the existing single-replica procedure.
   Only the new rows should be inserted; never invoke the general seed command.
4. Verify the exact fictional profile/material, no additional uploads/links, new
   allowlist/grants and Secret configuration before any real analysis request.
   Apply neither Secret nor Deployment patch during preparation.
5. Retain the model's service authentication, network isolation, browser session
   controls and synthetic gates. Verify HTTPS/Origin/CSRF and real local-service
   integration after a separately authorized rollout.

**Public/unattended use remains a blocker:** legacy profile/upload APIs rely on
mock role selection and do not establish real-user authorization. A visitor could
replace/add evidence for an allowlisted subject. This preparation does not freeze
that record or retrofit authentication onto those APIs. Thus fabricated initial
data alone cannot guarantee that later submissions remain synthetic. Use only an
operator-controlled synthetic demo with verified content, or a separately isolated
synthetic instance; do not treat a mixed public database as certified synthetic.
There is no approval here to process real applicant information.

Adding a candidate naturally adds one directory/discovery subject and may affect
aggregate counts. No existing matching/scoring algorithm, records, swipes or
percentages are changed by the setup. AI findings never populate candidate skills.
