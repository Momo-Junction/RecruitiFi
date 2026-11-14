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

This hackathon demo uses individual password-free demo accounts with shared API access (see below). Real deployment requires authenticated candidate ownership and authorized document access before handling real personal documents.

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

Set `TALENTMATCH_DB` to use a different database file. The default CORS origins are `http://localhost:5173` and `http://127.0.0.1:5173`. Set `TALENTMATCH_CORS_ORIGINS` to a comma-separated list for other origins. Set `VITE_API_URL` in `frontend/.env` to point the frontend to a different API base URL.

## Swipe discovery

Talent and Employer views open with a swipe deck ranked by the existing matching engine (dealbreakers first, then score). Drag a card right to like or left to pass, use the action buttons, or focus a card and press the arrow keys. Shared skills are highlighted; missing skills and meeting blockers stay visible. Profile edits recalculate Talent recommendations. On mobile, discovery appears before the profile editor.

Likes and passes persist in SQLite per demo candidate, company, and side. The Likes tab distinguishes pending interest from mutual likes. Undo restores the last swiped card. A mutual like records interest; meeting acceptance still follows the existing eligibility checks. Employer cards keep candidate identities anonymous.

- `GET /api/swipes` reads saved demo decisions.
- `PUT /api/swipes` upserts `{candidate_id, company_id, actor, decision}` (`actor`: `talent` or `employer`; `decision`: `like` or `pass`).
- `DELETE /api/swipes/{actor}/{candidate_id}/{company_id}` undoes one side's decision.

Restart the backend after upgrading; startup creates the swipe table without reseeding. These endpoints use the selected demo account's candidate/company IDs; this is not secure per-user authentication. Talent profile edits persist to that candidate; employer scores use saved profiles. Production use needs authenticated identity and access control. Decisions refresh immediately after a local action and poll every 12 seconds while a Talent or Employer dashboard is active.

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

A freshly seeded event has no saved proof materials, so legacy skills receive
self-declared evidence and no CV/portfolio points. Scores remain below the seeded
thresholds. Organizer suggestions require skill/language/visa eligibility and the
employer threshold, not likes or swipes. Add supporting synthetic materials and
refresh suggestions; do not lower thresholds to manufacture introductions.

## Individual demo accounts and profile isolation

At `/`, select Talent, Employer or Espoo Organizer, select an account, then click
**Enter Dashboard**. The existing `/talent`, `/employer` and `/organizer` dashboards
are reused. The header identifies the account and offers **Logout / Switch Account**.
The personal profile selectors are removed; discovery still includes all eight
companies and the existing anonymous candidate rankings.

The single server mapping in `backend/demo_accounts.py` is identical locally and
in the image. It looks up existing profiles without creating or updating records.
`GET /api/demo/accounts` returns account names, availability and actual event counts.
Missing profiles are explicitly unavailable, never replaced with another profile.
An empty database does not trigger seeding through the account endpoint.

| Talent account | Candidate ID | Seeded display name |
| --- | --- | --- |
| talent-001 | 402 | Aino Lehtinen |
| talent-002 | 406 | Samir Haddad |
| talent-003 | 411 | Nhi Tran |
| talent-004 | 417 | Oskari Niemi |
| talent-005 | 423 | Fatima Okafor |
| talent-006 | 429 | Linnea Holm |
| talent-007 | 432 | Mateo Rojas |
| talent-008 | 438 | Iryna Kovalenko |
| talent-009 | 445 | Joonas Salmi |
| talent-010 | 451 | Priya Menon |
| talent-011 | 458 | Elina Mäkinen |
| talent-012 | 463 | Min-jun Park |
| talent-013 | 470 | Sara Lindström |
| talent-014 | 476 | Lina Benali |
| talent-015 | 483 | Noah Weber |

| Employer account | Company ID | Seeded display name |
| --- | --- | --- |
| employer-001 | 1 | Kide Quantum Labs |
| employer-002 | 2 | Kallio Grid Energy |
| employer-003 | 3 | Siltava Health Systems |
| employer-004 | 4 | Ranta Cloud Works |
| employer-005 | 5 | Luoto Digital Studio |

`organizer-001` is **Espoo Organizer Admin**, with no candidate/company identity.
Companies 6–8 remain unchanged and discoverable, with no Employer login accounts.
Account display names are read from the current matching database records.

One shared session in `sessionStorage` under `recruitifi.demoAccount` stores the
account ID, role and candidate/company ID. Refresh validates that identity against
the server catalog before mounting a dashboard. Old role-only sessions require
account selection once after upgrading. Browser back/forward resolves to the
currently selected role; logout clears the account. Account changes unmount the
whole dashboard, abort reads and discard profile, directory, swipe and notification
state before the next account mounts. With browser storage disabled, selection
works in memory until refresh; refresh persistence requires sessionStorage.

Frontend API requests send `X-Recruitifi-Demo-Account` and bypass browser response caching with `cache: no-store`. Client checks reject a
mismatched profile/company ID, and the server independently checks the canonical
mapping before profile/document operations, company edits/meeting acceptance,
swipes/undo, or notification access. Candidate listing with this header returns
only the Talent's own profile, or no personal candidate records for other roles;
swipe listing returns only the selected profile's pairs. Anonymous matching
responses do not contain documents, email or full names. Matching calculations,
thresholds, Organizer eligibility, and notification rules are unchanged.

**These accounts are not secure authentication.** The account ID is caller-selected
and can be changed. Existing shared API calls without the header remain supported,
and direct document links do not carry it. Anyone with demo access can choose any
account or use shared API routes, including writes and document downloads. These
checks prevent accidental cross-account UI edits; they do not protect real personal
data. Use synthetic information only. The existing optional hosted Basic gate is
unchanged and, when enabled, still requires the shared password before accessing
accounts, APIs and downloads. No passwords or tokens are added to the account map.

There are **no database/schema migrations** for accounts. Do not rerun the seed
script on an existing event: it updates seed records. No PVC, Secret, environment,
Dockerfile, or Kubernetes resource changes are required.

To test locally, use the existing backend environment and two terminals:

```sh
# For a new disposable local event ONLY, not an existing/PVC database:
DEMO_DATA_DIR=$(mktemp -d "${TMPDIR:-/tmp}/recruitifi-demo.XXXXXX")
export TALENTMATCH_DB="$DEMO_DATA_DIR/event.sqlite3"
backend/.venv/bin/python -m backend.seed
backend/.venv/bin/python -m uvicorn backend.main:app --reload
# Other terminal:
cd frontend
pnpm dev
```

Open http://localhost:5173. Select `talent-001`, confirm Aino's profile without a
persona dropdown, edit a skill/upload a synthetic document and refresh. Log out;
select `talent-002` and verify its own editor and empty/separate inbox. Test
`employer-001`, then `employer-002`, confirming the company is fixed in each editor.
Talent likes produce only the corresponding Employer Interested badge; Employer
likes notify that Talent; both likes notify only the pair. Use another tab to test
polling. Select `organizer-001` to verify the existing planner. Check direct URLs,
back/forward and logout. Local tests use disposable SQLite files only.

Validation commands:

```sh
backend/.venv/bin/python -m unittest discover -s backend -t . -p 'test_*.py' -v
(cd frontend && npm test && npm run build)
docker buildx build --platform linux/amd64 --load -t recruitifi:demo-accounts .
python3 -B deploy/rahti/test_container.py recruitifi:demo-accounts
```

Rebuild/rollout instructions preserving the existing SQLite data are in
[deploy/rahti/README.md](deploy/rahti/README.md#installing-individual-demo-accounts).

## Interest indicators and notifications

Incoming Talent likes show **Interested** on the matching Employer's candidate
cards, including the queue and saved likes. They do not create Employer interest
notifications. Employer likes create an interest notification for that Talent.
When both current likes exist, each side receives **It's a Match!**; the earlier
Talent interest alert is superseded. Compatibility scores and Organizer eligibility
are unchanged: a mutual like is interest, not automatic meeting eligibility.

The bell belongs to the logged-in demo candidate or company, not just the demo
role. It shows active notifications, timestamps and unread counts, with individual
Mark read controls. Active dashboards poll every 12 seconds and refresh immediately
after local swipes, undo or read actions. Switching identities remounts the inbox;
old requests are aborted. These frontend demo identities do not provide secure
per-user authorization. Everyone with shared demo access can select another account after logout;
use synthetic information only.

Startup adds the `notifications` table and indexes using repeatable CREATE IF NOT
EXISTS statements. Existing candidates, companies, skills, swipes and document
BLOBs are not reset. Existing likes are backfilled on startup; their notification
timestamp is the backfill time because legacy swipes have no timestamp. Active
read/unread state is preserved across subsequent restarts.

Each pair has at most one row per recipient/type. Repeated active likes preserve
notification ID, timestamp and read state. Withdrawal or supersession marks rows
inactive and removes them from active inboxes. Renewed interest reactivates the
same row with a new timestamp and unread state. Stored history is bounded to the
last activation per pair/recipient/type, not a full chronological activity log.
Swipe writes/undo and notification reconciliation share one SQLite transaction;
concurrent writers serialize with BEGIN IMMEDIATE. No new external service is used.

API additions:

- `GET /api/notifications/{recipient}/{identity_id}` returns active `entries` and
  `unread_count`; recipient is `talent` (candidate ID) or `employer` (company ID).
- `PUT /api/notifications/{recipient}/{identity_id}/{notification_id}/read` marks
  an active scoped notification read and returns the refreshed inbox. Wrong
  identity or inactive IDs return 404.
- `PUT /api/swipes` retains its decision fields and adds `mutual_match` to the
  response; `GET /api/swipes` remains the persisted decision list for badges.
- Existing swipe DELETE also returns the remaining derived `mutual_match` state.

Run backend tests with `backend/.venv/bin/python -m unittest discover -s backend
-t . -p 'test_*.py' -v`, and `npm test && npm run build` in frontend. The container
checks also verify notification/read persistence across recreation alongside BLOB
persistence. See the existing Rahti runbook for backup and a single-image update;
never reseed or delete the PVC to install this additive migration.
