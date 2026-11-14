import json
import os
from typing import Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .database import SCHEMA_PATH, connect
from .hiring_tasks import router as hiring_router
from .matching_engine import LANGUAGE_LEVELS, SCORING_VERSION, calculate_match
from .models import (
    Candidate,
    CandidateProfile,
    Company,
    CompanyMatch,
    CompanyRoleUpdate,
    MatchSimulation,
    MeetingContact,
    PositiveId,
    RankedMatch,
    Skill,
    SwipeDecision,
)
from .profile_materials import candidate_profile, router as profile_router
from .hosting import configure_hosting, initialize_demo

COMPANY_JSON_FIELDS = ("must_have_skills", "nice_to_have_skills")
CANDIDATE_JSON_FIELDS = ("languages", "skills")


@asynccontextmanager
async def lifespan(app: FastAPI):
    with connect() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute(
            "UPDATE skills SET name = ? WHERE name = ?",
            ("Quantum circuit programming with Qiskit", "Quantum Computing"),
        )
    initialize_demo()
    yield


app = FastAPI(title="City of Espoo TalentMatch", lifespan=lifespan)
app.include_router(profile_router)
app.include_router(hiring_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get(
            "TALENTMATCH_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


def read_rows(query: str, *json_fields: str, params: tuple = ()):
    with connect() as connection:
        return list(decode_rows(connection.execute(query, params), json_fields))


def decode_rows(rows, json_fields):
    for row in rows:
        values = dict(row)
        for field in json_fields:
            values[field] = json.loads(values[field])
        yield values


@app.get("/api/skills", response_model=list[Skill])
def list_skills():
    return read_rows("SELECT * FROM skills ORDER BY id")


@app.get("/api/companies", response_model=list[Company])
def list_companies():
    return read_rows(
        "SELECT * FROM companies ORDER BY id", *COMPANY_JSON_FIELDS
    )


@app.get("/api/candidates", response_model=list[Candidate])
def list_candidates():
    with connect() as connection:
        ids = [row["id"] for row in connection.execute("SELECT id FROM candidates ORDER BY id")]
        return [candidate_profile(connection, candidate_id)["candidate"] for candidate_id in ids]


@app.get('/api/swipes', response_model=list[SwipeDecision])
def list_swipes():
    return read_rows('SELECT * FROM swipe_decisions ORDER BY candidate_id, company_id, actor')


@app.put('/api/swipes', response_model=SwipeDecision)
def save_swipe(swipe: SwipeDecision):
    with connect() as connection:
        if swipe.actor == 'employer' and swipe.decision == 'pass':
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute(
                "SELECT 1 FROM hiring_tasks WHERE candidate_id = ? AND company_id = ? LIMIT 1",
                (swipe.candidate_id, swipe.company_id),
            ).fetchone():
                raise HTTPException(409, "This candidate has assigned tasks. Their shortlist decision is locked.")
        if not connection.execute('SELECT 1 FROM candidates WHERE id = ?', (swipe.candidate_id,)).fetchone():
            raise HTTPException(status_code=404, detail='Candidate not found.')
        if not connection.execute('SELECT 1 FROM companies WHERE id = ?', (swipe.company_id,)).fetchone():
            raise HTTPException(status_code=404, detail='Company not found.')
        connection.execute(
            'INSERT INTO swipe_decisions (candidate_id, company_id, actor, decision) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(candidate_id, company_id, actor) DO UPDATE SET decision = excluded.decision',
            (swipe.candidate_id, swipe.company_id, swipe.actor, swipe.decision),
        )
    return swipe


def get_company(company_id: int) -> Company:
    rows = read_rows(
        "SELECT * FROM companies WHERE id = ?", *COMPANY_JSON_FIELDS, params=(company_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Company not found.")
    return Company.model_validate(rows[0])


def read_skill_names() -> dict[int, str]:
    return {row["id"]: row["name"] for row in read_rows("SELECT id, name FROM skills")}


@app.put("/api/companies/{company_id}/role", response_model=Company)
def update_company_role(company_id: PositiveId, role: CompanyRoleUpdate):
    company = get_company(company_id)
    unknown_ids = sorted(
        {skill.skill_id for skill in role.must_have_skills + role.nice_to_have_skills}
        - read_skill_names().keys()
    )
    if unknown_ids:
        raise HTTPException(status_code=422, detail=f"Unknown skill IDs: {unknown_ids}.")
    values = role.model_dump()
    with connect() as connection:
        connection.execute(
            """UPDATE companies SET working_language = ?, relocation_support = ?,
               min_match_threshold = ?, must_have_skills = ?, nice_to_have_skills = ?
               WHERE id = ?""",
            (
                role.working_language, role.relocation_support, role.min_match_threshold,
                json.dumps(values["must_have_skills"]), json.dumps(values["nice_to_have_skills"]),
                company_id,
            ),
        )
    return Company.model_validate({**company.model_dump(), **values})


def score_for_company(candidate: CandidateProfile, company: Company, skill_names: dict[int, str]):
    result = calculate_match(candidate, company, skill_names=skill_names)
    return {
        **result,
        "company_id": company.id,
        "min_match_threshold": company.min_match_threshold,
        "meets_threshold": result["total_score"] >= company.min_match_threshold,
    }


def audit_score(candidate: CandidateProfile, company: Company, result: dict, source: str):
    language = company.working_language.strip().casefold()
    levels = [
        level for name, level in candidate.languages.items() if name.strip().casefold() == language
    ]
    inputs = {
        "scoring_version": SCORING_VERSION,
        "working_language": company.working_language,
        "minimum_language_level": "B2",
        "candidate_language_level": max(levels, key=LANGUAGE_LEVELS.get, default=None),
        "needs_visa_sponsorship": candidate.needs_visa_sponsorship,
        "relocation_support": company.relocation_support,
        "has_cv": candidate.has_cv,
        "has_portfolio": candidate.has_portfolio,
    }
    return (
        source, company.name, getattr(candidate, "anonymous_code", None),
        json.dumps(inputs), json.dumps({
            key: value for key, value in result.items() if key != "improvement_hints"
        }),
    )


def write_audit(entries):
    with connect() as connection:
        connection.executemany(
            "INSERT INTO match_audit (source, company_name, candidate_code, inputs, result) "
            "VALUES (?, ?, ?, ?, ?)", entries,
        )


@app.post("/api/match/simulate", response_model=CompanyMatch)
def simulate_match(simulation: MatchSimulation):
    company = get_company(simulation.company_id)
    skill_names = read_skill_names()
    unknown_ids = sorted({skill.skill_id for skill in simulation.candidate.skills} - skill_names.keys())
    if unknown_ids:
        raise HTTPException(status_code=422, detail=f"Unknown skill IDs: {unknown_ids}.")
    result = score_for_company(simulation.candidate, company, skill_names)
    write_audit([audit_score(simulation.candidate, company, result, "simulation")])
    return result


@app.get("/api/companies/{company_id}/matches", response_model=list[RankedMatch])
def rank_company_matches(company_id: PositiveId):
    company = get_company(company_id)
    skill_names = read_skill_names()
    matches = []
    entries = []
    for row in list_candidates():
        candidate = Candidate.model_validate(row)
        result = score_for_company(candidate, company, skill_names)
        entries.append(audit_score(candidate, company, result, "employer_queue"))
        matches.append({
            **result,
            "candidate_id": candidate.id,
            "anonymous_code": candidate.anonymous_code,
        })
    write_audit(entries)
    matches.sort(key=lambda match: (
        not match["dealbreakers_passed"], -match["total_score"], match["candidate_id"]
    ))
    return [{"rank": rank, **match} for rank, match in enumerate(matches, start=1)]


@app.post(
    "/api/companies/{company_id}/matches/{anonymous_code}/accept",
    response_model=MeetingContact,
)
def accept_meeting(company_id: PositiveId, anonymous_code: str, human_reviewed: bool = False):
    company = get_company(company_id)
    rows = read_rows(
        "SELECT * FROM candidates WHERE anonymous_code = ?", *CANDIDATE_JSON_FIELDS,
        params=(anonymous_code,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    with connect() as connection:
        candidate = Candidate.model_validate(candidate_profile(connection, rows[0]["id"])["candidate"])
    match = score_for_company(candidate, company, read_skill_names())
    match["human_reviewed"] = human_reviewed
    write_audit([audit_score(candidate, company, match, "meeting_review")])
    if not human_reviewed and not (match["dealbreakers_passed"] and match["meets_threshold"]):
        raise HTTPException(status_code=409, detail="Candidate no longer meets the role requirements.")

    verified = sorted(
        (
            skill for skill in match["must_have_skills"] + match["nice_to_have_skills"]
            if skill["evidence_tier"] == "certificate"
        ),
        key=lambda skill: (-skill["weight"], skill["skill_id"]),
    )
    names = list(dict.fromkeys(skill["skill_name"] for skill in verified))[:2]
    starter = (
        "Shared skills with submitted certificates: " + " & ".join(names)
        if names else "Ask about a recent project using one of the role’s skills."
    )
    return MeetingContact(
        full_name=candidate.full_name, email=candidate.email, conversation_starter=starter
    )


@app.post("/api/audit/metrics")
def calculate_event_metrics():
    # Use one read snapshot so each card describes the same set of profiles and roles.
    with connect() as connection:
        connection.execute("BEGIN")
        companies = [
            Company.model_validate(row) for row in decode_rows(
                connection.execute("SELECT * FROM companies ORDER BY id"), COMPANY_JSON_FIELDS,
            )
        ]
        ids = [row["id"] for row in connection.execute("SELECT id FROM candidates ORDER BY id")]
        candidates = [Candidate.model_validate(candidate_profile(connection, candidate_id)["candidate"]) for candidate_id in ids]
        skill_names = {row["id"]: row["name"] for row in connection.execute("SELECT id, name FROM skills")}

    entries = []
    total_tenths = 0
    passed_dealbreakers = 0
    below_threshold = 0
    for company in companies:
        for candidate in candidates:
            result = score_for_company(candidate, company, skill_names)
            entries.append(audit_score(candidate, company, result, "event_metrics"))
            total_tenths += round(result["total_score"] * 10)
            if result["dealbreakers_passed"]:
                passed_dealbreakers += 1
                below_threshold += not result["meets_threshold"]
    write_audit(entries)
    return {
        "talent_count": len(candidates),
        "company_count": len(companies),
        "pair_count": len(entries),
        "average_score": round(total_tenths / (10 * len(entries)), 1) if entries else None,
        "passed_dealbreakers": passed_dealbreakers,
        "below_threshold": below_threshold,
        "filtered_percent": round(100 * below_threshold / passed_dealbreakers, 1) if passed_dealbreakers else None,
    }


@app.get("/api/audit/calculations")
def list_audit_calculations(
    before_id: PositiveId | None = None, limit: int = Query(20, ge=1, le=100),
):
    rows = read_rows(
        """SELECT * FROM match_audit WHERE (? IS NULL OR id < ?)
           ORDER BY id DESC LIMIT ?""",
        "inputs", "result", params=(before_id, before_id, limit + 1),
    )
    return {"entries": rows[:limit], "next_before_id": rows[limit - 1]["id"] if len(rows) > limit else None}


@app.delete('/api/swipes/{actor}/{candidate_id}/{company_id}')
def undo_swipe(actor: Literal['talent', 'employer'], candidate_id: PositiveId, company_id: PositiveId):
    with connect() as connection:
        if actor == 'employer':
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute(
                "SELECT 1 FROM hiring_tasks WHERE candidate_id = ? AND company_id = ? LIMIT 1",
                (candidate_id, company_id),
            ).fetchone():
                raise HTTPException(409, "This candidate has assigned tasks. Their shortlist decision is locked.")
        connection.execute(
            'DELETE FROM swipe_decisions WHERE actor = ? AND candidate_id = ? AND company_id = ?',
            (actor, candidate_id, company_id),
        )
    return {'deleted': True}


@app.get("/healthz", include_in_schema=False)
def health():
    with connect() as connection:
        connection.execute("SELECT id FROM candidates LIMIT 1").fetchone()
    return {"status": "ok"}


configure_hosting(app)
