# City of Espoo TalentMatch

A demo event directory with a FastAPI and SQLite backend and a React, TypeScript, Vite, and Tailwind CSS frontend. The seed data includes 40 skills, 8 fictional Espoo employers, and 15 synthetic candidates.

## Run locally

Use Python 3.11 or newer and Node.js 22.12 or newer. Run these commands from the repository root in PowerShell.

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
backend/.venv/Scripts/python.exe -m backend.seed
backend/.venv/Scripts/python.exe -m uvicorn backend.main:app --reload
```

On macOS or Linux use `backend/.venv/bin/python` for the virtual environment executable.

In a second terminal, start the frontend.

```sh
cd frontend
pnpm install
pnpm dev
```

Open the [event directory](http://localhost:5173/) or [interactive API docs](http://127.0.0.1:8000/docs). Run `pnpm build` from `frontend` to type-check and build the app.

## Deploy the shared demo

1. In the [Render dashboard](https://dashboard.render.com/), choose **New → Blueprint**, connect `Momo-Junction/RecruitiFi`, and select `main`.
2. Enter a strong `TALENTMATCH_DEMO_PASSWORD` when prompted and review the cost of the paid web service and persistent disk before creating the resources.
3. Open the HTTPS URL Render assigns. Sign in with username `demo` and the password you set. The same service hosts the UI and API. The first startup seeds synthetic data, and subsequent starts use the database on `/var/data`.
4. Upload a synthetic PDF, download it, restart the service, and confirm it is still available. Check a swipe and undo, employer scoring, and the organizer view before sharing the URL.

The shared password gives viewers access to all demo personas. Use synthetic documents for this deployment.

## API and data

Talent profiles have dedicated sections for CVs, projects, certificates, research, LinkedIn, GitHub and personal websites. Uploaded PDF, PNG and JPEG files (up to 10 MB each) and link metadata are stored in SQLite. Downloading a document returns it as an attachment.

CV and portfolio availability are derived from saved materials. Skills linked to projects, research or submitted certificates receive the corresponding scoring tier. A submitted certificate has a reviewable attachment or URL, and its authenticity requires human review. Legacy seeded skill claims are treated as listed skills until supporting material is attached.

This local hackathon demo uses a persona selector and unauthenticated API routes. Real deployment requires authenticated candidate ownership and authorized document access before handling real personal documents.

| Endpoint | Returns |
| --- | --- |
| `GET /api/skills` | Skill catalog with names, categories, and local ESCO-style URI placeholders |
| `GET /api/companies` | Employer booths, working languages, relocation support, match thresholds, and weighted skill requirements |
| `GET /api/candidates` | Synthetic candidate records with language levels and skill evidence |
| `POST /api/match/simulate` | Scores a temporary candidate profile in memory |
| `GET /api/companies/{company_id}/matches` | Scores and ranks all seeded candidates for an employer |
| `POST /api/audit/metrics` | Recalculates current event metrics and records the calculation batch |
| `GET /api/audit/calculations` | Lists recorded calculations, newest first, with cursor pagination |

The organizer dashboard averages scores across all saved candidate–company pairs. Its threshold filter rate divides the number of below-threshold pairs by the number of pairs that passed both dealbreakers. Temporary Talent simulations appear in the log and are excluded from event metrics. SQLite records the relevant input values, rule version, per-skill math, and outcome for calculations made through the app after audit logging is enabled.

The matching engine uses fixed rules. It reports dealbreakers separately from the numeric score and shows the points for each skill and profile proof. Improvement gains reflect the exact score increase for the action shown. Adding a missing skill with a certificate gives its full weight. Duplicate candidate skill entries use the strongest evidence.

Rankings place candidates who pass the dealbreakers first, then sort by descending score and ascending candidate ID. The `meets_threshold` field checks the numeric employer threshold independently of the dealbreakers.

To simulate a match, send JSON like this to `POST /api/match/simulate`:

```json
{
  "company_id": 8,
  "candidate": {
    "has_cv": true,
    "has_portfolio": false,
    "languages": {"English": "B2"},
    "needs_visa_sponsorship": false,
    "skills": [{"skill_id": 3, "evidence_tier": "portfolio"}]
  }
}
```

The seed script creates `backend/talentmatch.sqlite3`. Rerunning it updates the same demo records by ID. Skill requirements use `{skill_id, weight}` and total 70 for must-have skills and 20 for nice-to-have skills per company. Candidate skills use `{skill_id, evidence_tier}` with `self_declared`, `portfolio`, or `certificate`.

The `esco_uri` values are local identifiers for the demo. Candidate emails use `example.com`. The UI displays candidate codes while the demo API returns the full synthetic records.

Set `TALENTMATCH_DB` to use a different database file. The default CORS origins are `http://localhost:5180` and `http://127.0.0.1:5180`. Set `TALENTMATCH_CORS_ORIGINS` to a comma-separated list for other origins. Set `VITE_API_URL` in `frontend/.env` to point the frontend to a different API base URL.

## Swipe discovery

Talent and Employer views open with a swipe deck ranked by the existing matching engine (dealbreakers first, then score). Drag a card right to like or left to pass, use the action buttons, or focus a card and press the arrow keys. Shared skills are highlighted; missing skills and meeting blockers stay visible. Profile edits recalculate Talent recommendations. On mobile, discovery appears before the profile editor.

Likes and passes persist in SQLite per demo candidate, company, and side. The Likes tab distinguishes pending interest from mutual likes. Undo restores the last swiped card. A mutual like records interest; meeting acceptance still follows the existing eligibility checks. Employer cards keep candidate identities anonymous.

Identity is shared only with consent. An employer's meeting request (`POST /api/companies/{company_id}/matches/{anonymous_code}/accept`) records the employer's like and returns `revealed: false` with no name or email. Only when the candidate has also liked that company does it return `revealed: true` with the candidate's name and email. On the Talent side, "I'd like to meet" in an employer's match breakdown saves that like.

- `GET /api/swipes` reads saved demo decisions.
- `PUT /api/swipes` upserts `{candidate_id, company_id, actor, decision}` (`actor`: `talent` or `employer`; `decision`: `like` or `pass`).
- `DELETE /api/swipes/{actor}/{candidate_id}/{company_id}` undoes one side's decision.

Restart the backend after upgrading; startup creates the swipe table without reseeding. Like the rest of this demo, these endpoints use shared personas without authentication. Talent profile edits remain temporary simulations; employer scores use saved seed profiles. Production use needs authenticated identity and access control. Decisions update across both views in the current page; reload to fetch changes from another browser.

Run the isolated swipe API checks with `backend/.venv/bin/python -m unittest backend.test_swipes`.

## Container and Rahti infrastructure

See [the Rahti deployment runbook](deploy/rahti/README.md) for local container
checks, persistence, manifests and backup/restore commands. The container serves
the built frontend and API on port 8080, with SQLite at `/var/data/talentmatch.sqlite3`.
Production frontend builds use same-origin `/api` requests; Vite development keeps
the localhost API default. `/healthz` reports process health after startup.

Hosted mode (`TALENTMATCH_HOSTED_DEMO=1`) protects the frontend, assets, API,
documentation and downloads with HTTP Basic authentication: username `demo`,
password from `TALENTMATCH_DEMO_PASSWORD` (a Kubernetes Secret on Rahti). Missing
password configuration stops startup; invalid request credentials return 401.
`/healthz` remains public for probes. Use HTTPS and synthetic information only;
shared access is not a candidate account/ownership system. Local development is
unchanged when hosted mode is unset or 0. Actual Rahti SCC, PVC and HTTPS operation
still require a later authorized cluster test. Render deployment settings are in `render.yaml`.

## Hackathon public access and Organizer suggestions

Hosted authentication is enabled by default. Explicitly set
`TALENTMATCH_DEMO_AUTH_ENABLED=false` for password-free public access; use `true`
or omit it to require the existing shared password. Keep the Secret for later use.
Public access also permits shared data changes and document access: synthetic data
only. See [the hackathon runbook](deploy/rahti/README.md#optional-password-free-hackathon-mode)
for safe update commands and a legitimate Organizer demonstration.

The seed attaches clearly labelled synthetic proof to each persona: a one-page PDF
CV and `https://example.com/talentmatch-demo/` project and certificate links that
match the evidence in `backend/seed_data.py`. A freshly seeded event therefore opens
with evidence-backed introductions at seven of the eight booths. Kuura Software has
none because its strongest candidate needs visa sponsorship, which shows the
"booths that may need help" view and the employer's human-review override.
Reseeding replaces only these synthetic materials and keeps anything users added.
Organizer suggestions require skill/language/visa eligibility and the employer
threshold, not likes or swipes. Deleting a persona's proof drops the same skills
back to listed-skill evidence and below the threshold; do not lower thresholds to
manufacture introductions.
