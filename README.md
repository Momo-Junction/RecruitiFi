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

## API and data

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
