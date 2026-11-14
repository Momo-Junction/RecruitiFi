# Presentation walkthrough

The completed presentation path uses the existing verified application login and
private MiniLM service. Sign in once; no additional password is requested inside
the AI feature. Use only the newly provisioned fictional account, not 402 or 406.

1. Select Talent → `talent-ai-001`; enter its supplied application password.
2. Click **Analyze My Profile** above Projects & portfolio. This analyzes the
   explicitly fabricated project, computes selected-job evidence coverage with
   MiniLM, and updates existing job/swipe cards. Allow the background job to finish.
3. Open **Why this match?** to show relevant evidence, source material IDs,
   claimed-only/missing requirements and unreviewed labels. Select a different
   job/industry to demonstrate different weighted model scores.
4. Logout, select Employer → `employer-001`, and enter that application's password.
   The same scores appear for candidate 900001 under its selected job. Other
   candidates display **Not analyzed**, not made-up rule-based AI percentages.
5. Likes, passes and notifications retain the existing company-level behavior.
   Meetings remain subject to existing human review; AI is not a hiring decision.
   Explore all Talent if the fictional candidate is below a meeting threshold.

Passwords are supplied in a protected local presenter file, never this repository.
No provider, second login system, model token or browser-stored privileged token
is required. The existing signed HttpOnly session verifies Talent/Employer identity;
server-side Employer grants control private score/excerpt reads.

## Score definition and honest interpretation

For requirement i, let c_i be its highest cosine similarity against the bounded
sample of approved evidence fragments. Coverage q_i = clamp((c_i-0.20)/0.45,0,1).
The displayed percentage is 100 × sum(w_i × q_i)/sum(w_i), using each job's existing
required/preferred weights. Duplicate skill weights are combined. There are no
CV-presence bonuses, fabricated skills, keyword-only percentages or legacy-score
fallbacks. Missing evidence/model failures produce no AI score. Claimed skills
without supporting relevance contribute zero. Raw cosine is not a hiring probability.

The anchors 0.20/0.65 are transparent heuristic calibration, **not empirically
validated accuracy or proficiency thresholds**. False positives remain possible.
All findings are unreviewed; treat them as conversation aids. Source metadata,
CV text and README text are untrusted data, never executed or followed as instructions.

## Processing and privacy

The existing isolated worker provides one global analysis at a time, absolute
termination timeout and bounded result size. Approved evidence is capped to three
materials/10MiB total, existing PDF limits (10 pages/20,000 characters; no OCR),
six 200-character embedding fragments and at most 32 active jobs. Requirement
embeddings are shared within each analysis (max 106 distinct inputs, batches ≤3).
The UI explicitly describes bounded sampling; this is not exhaustive CV review.

The additive `ai_profile_matches` table stores source-run-linked cached results.
Fingerprinting covers approved material contents/metadata, claims, skill catalog,
job requirements and model/scoring versions. Stale scores disappear immediately
when queried. Job changes trigger recomputation while the owning Talent is viewing
the page; failures never fall back to old fit percentages. Unapproved fixture
changes require operator review, not automatic analysis. Deleting a source analysis
invalidates the linked cache via foreign keys. Existing candidate skills, swipes,
notifications and matching audit records are not rewritten by AI scoring.

No existing private CV is automatically analyzed. Candidate 900001 must exactly
match the fabricated fixture. Other profiles require the existing synthetic
allowlist **and** explicit server-only `TALENTMATCH_AI_MATCH_MATERIALS` JSON mapping
candidate IDs to approved existing material IDs (max three), followed by their
verified Talent's Analyze action. CV/project text and controlled public GitHub
README retrieval are supported; LinkedIn/website links alone are not evidence.
Do not add real data to this demo configuration. Real applicant deployment still
requires production identity, durable consent and retention/revocation hardening.

## Application configuration (model Deployment unchanged)

```text
TALENTMATCH_VERIFIED_DEMO_LOGIN=1
TALENTMATCH_AI_JOB_MATCHING=1
TALENTMATCH_AI_PUBLIC_DEMO=0
TALENTMATCH_AI_SYNTHETIC_DEMO=1
TALENTMATCH_AI_SYNTHETIC_CANDIDATES=900001
TALENTMATCH_AI_EMPLOYER_ACCESS={"1":[900001]}
TALENTMATCH_PUBLIC_ORIGIN=https://<actual-application-route-host>
```

Reuse the protected application account-password map, independent signing/operator
secrets and `recruitifi-ai-auth` service token through Secret references. The fixed
canonical HTTPS origin fixes edge-termination comparison while retaining exact
Origin and Host checks and Secure cookies; no wildcard forwarded-header trust is
added. Hosted Basic auth and existing PVC/resources/probes/Recreate are retained.
Organizer remains its original preview; the verified login is for Talent/Employer.

Build the updated root Dockerfile for linux/amd64, publish an immutable digest,
snapshot the existing Deployment privately and use a resourceVersion-guarded patch
for the image and these explicit settings. Never delete/reseed the PVC, modify the
model Deployment, or automatically analyze the existing applicant directory.
Keep a SQLite backup and previous image reference before an authorized rollout.

Validation commands:

```sh
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py'
(cd frontend && npm test && npm run build)
docker buildx build --platform linux/amd64 --load -t recruitifi:presentation-complete .
```
