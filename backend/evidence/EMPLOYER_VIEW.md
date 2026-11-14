# Synthetic Employer evidence view

This documents the retained session-protected endpoint. The current Employer UI
uses the separate opt-in constant-fixture public route described in
`deploy/rahti/ai/PUBLIC_DEMO.md`, with no extra AI login or configurable grants.

The read-only endpoint is:
`GET /api/companies/{company_id}/candidates/{candidate_id}/evidence-analysis`.

Existing synthetic-mode/operator-token/candidate-allowlist and browser-session
settings remain mandatory. Add distinct Employer passwords to the server-only
`TALENTMATCH_AI_DEMO_ACCOUNTS` JSON map (e.g. an `employer-001` key). That map
supports up to 20 Talent/Employer identities; Organizers are not admitted.
Never reuse the operator/signing secret as an account password.

Explicit sharing is configured only on the server:

```text
TALENTMATCH_AI_EMPLOYER_ACCESS={"1":[402,406],"2":[411]}
```

These candidate IDs must also be in `TALENTMATCH_AI_SYNTHETIC_CANDIDATES` and
represent synthetic records in an isolated database. No grants means no Employer
access. This is an operator-approved sharing policy, not inferred from job-fit,
swipes, notifications or caller-selected role headers.

The existing password/HttpOnly/SameSite/HTTPS-cookie login verifies the Employer
account; the endpoint checks its company ID and the exact candidate grant.
Changing company/candidate paths or mock role selection cannot grant access.
An operator-token header alone does not authenticate this Employer read endpoint.
Employer sessions cannot trigger Talent analyses. Existing trusted internal
operator analysis controls remain unchanged.

Only the newest stored run per material is considered (bounded to 50 recent runs).
Completed/limited findings are returned with their original review status and
separate observation/semantic kinds. Uploaded PDFs/images/unsupported files retain
only skill findings and internal source/run IDs, with a private-document label;
their excerpts/filenames/download paths are withheld. Only approved synthetic
project-link metadata and public GitHub-derived excerpts/references are shared.
No document BLOBs are selected, no inference runs, and no SQLite records change.
Historical runs outside the bounded window are intentionally not included.

The response contains `status` (missing/pending/running/completed/failed) and
`analyses`, containing normalized storage results. Pending/failed jobs can coexist
with earlier completed findings; the UI says so explicitly. The Employer panel
is read-only and offers manual refresh, never analysis triggers or mutations.
It reuses EvidenceAnalysis and displays cosine as relevance, not proficiency.
Accepted/rejected human review labels are distinct from proficiency verification.

The feature stays hidden when browser sessions are disabled. Authentication,
sharing failures and missing results produce clear messages. Browser credentials
stay transient, and operator/signing secrets never enter frontend build variables
or browser storage. Source text remains untrusted and escaped by React.

This is synthetic hackathon authentication only. Existing non-analysis mock APIs
are not converted to production authorization. Session replay/revocation,
process-local login throttling, trusted HTTPS/proxy setup, privacy/consent and real
owner/Employer relationships still require production security work. See
BROWSER_SESSIONS.md for inherited limitations. Do not enable this on real data.
