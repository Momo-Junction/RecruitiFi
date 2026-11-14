"""Job-level requirement adapters; scoring and company-level interactions are unchanged."""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .database import connect
from .demo_accounts import request_account, require_owner
from .matching_engine import calculate_match
from .models import CompanyMatch, CompanyRequirements, PositiveId, RankedMatch
from .profile_materials import candidate_profile

Industry = Literal['it', 'business_services', 'logistics', 'health_sector', 'restaurant', 'cleaning', 'engineering']
INDUSTRIES = [
    {'id': 'it', 'label': 'IT'},
    {'id': 'business_services', 'label': 'Business (Services)'},
    {'id': 'logistics', 'label': 'Logistics'},
    {'id': 'health_sector', 'label': 'Health Sector'},
    {'id': 'restaurant', 'label': 'Restaurant'},
    {'id': 'cleaning', 'label': 'Cleaning'},
    {'id': 'engineering', 'label': 'Engineering'},
]
router = APIRouter(prefix='/api')


class JobOpening(CompanyRequirements):
    id: PositiveId
    company_id: PositiveId
    company_name: str
    title: str
    industry: Industry
    industry_label: str
    description: str
    active: bool
    min_match_threshold: int


class JobMatch(CompanyMatch):
    job_id: int


class JobRankedMatch(RankedMatch):
    job_id: int


def read_jobs(connection, *, company_id=None, industries=None, active_only=True, job_id=None):
    clauses, params = [], []
    if active_only:
        clauses.append('j.active=1')
    if company_id is not None:
        clauses.append('j.company_id=?')
        params.append(company_id)
    if job_id is not None:
        clauses.append('j.id=?')
        params.append(job_id)
    if industries:
        clauses.append('j.industry IN (' + ','.join('?' for _ in industries) + ')')
        params.extend(industries)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    rows = connection.execute(
        'SELECT j.*, c.name AS company_name, c.working_language, c.relocation_support, c.min_match_threshold '
        'FROM job_openings j JOIN companies c ON c.id=j.company_id' + where + ' ORDER BY j.id', params,
    )
    labels = {category['id']: category['label'] for category in INDUSTRIES}
    return [JobOpening.model_validate({**dict(row), 'industry_label': labels[row['industry']],
            'must_have_skills': json.loads(row['must_have_skills']),
            'nice_to_have_skills': json.loads(row['nice_to_have_skills'])}) for row in rows]


def score_job(candidate, job, skill_names):
    # JobOpening inherits the engine's existing CompanyRequirements input model.
    result = calculate_match(candidate, job, skill_names=skill_names)
    return {**result, 'job_id': job.id, 'company_id': job.company_id,
            'min_match_threshold': job.min_match_threshold,
            'meets_threshold': result['total_score'] >= job.min_match_threshold}


@router.get('/jobs/industries')
def industries():
    return INDUSTRIES


@router.get('/jobs', response_model=list[JobOpening])
def list_jobs(industry: list[Industry] | None = Query(default=None), company_id: PositiveId | None = None):
    with connect() as connection:
        if company_id is not None and not connection.execute('SELECT 1 FROM companies WHERE id=?', (company_id,)).fetchone():
            raise HTTPException(404, 'Company not found.')
        return read_jobs(connection, company_id=company_id, industries=industry)


@router.get('/companies/{company_id}/jobs', response_model=list[JobOpening])
def company_jobs(company_id: PositiveId, request: Request):
    require_owner(request_account(request), 'employer', company_id)
    with connect() as connection:
        if not connection.execute('SELECT 1 FROM companies WHERE id=?', (company_id,)).fetchone():
            raise HTTPException(404, 'Company not found.')
        return read_jobs(connection, company_id=company_id, active_only=False)


@router.get('/jobs/{job_id}', response_model=JobOpening)
def get_job(job_id: PositiveId):
    with connect() as connection:
        jobs = read_jobs(connection, job_id=job_id, active_only=False)
        if not jobs:
            raise HTTPException(404, 'Job opening not found.')
        return jobs[0]


@router.get('/jobs/{job_id}/matches', response_model=list[JobRankedMatch])
def rank_job(job_id: PositiveId, request: Request):
    with connect() as connection:
        jobs = read_jobs(connection, job_id=job_id, active_only=False)
        if not jobs:
            raise HTTPException(404, 'Job opening not found.')
        job = jobs[0]
        require_owner(request_account(request), 'employer', job.company_id)
        skill_names = {row['id']: row['name'] for row in connection.execute('SELECT id, name FROM skills')}
        matches = []
        for row in connection.execute('SELECT id FROM candidates ORDER BY id').fetchall():
            profile = candidate_profile(connection, row['id'])['candidate']
            matches.append({**score_job(profile, job, skill_names), 'candidate_id': profile['id'],
                            'anonymous_code': profile['anonymous_code']})
    # Preserve the existing company queue's dealbreaker-first and ID tie-break behavior.
    matches.sort(key=lambda item: (not item['dealbreakers_passed'], -item['total_score'], item['candidate_id']))
    return [{'rank': rank, **match} for rank, match in enumerate(matches, 1)]


@router.get('/candidates/{candidate_id}/job-matches', response_model=list[JobMatch])
def candidate_jobs(candidate_id: PositiveId, request: Request):
    require_owner(request_account(request), 'talent', candidate_id)
    with connect() as connection:
        profile = candidate_profile(connection, candidate_id)['candidate']
        names = {row['id']: row['name'] for row in connection.execute('SELECT id, name FROM skills')}
        matches = [score_job(profile, job, names) for job in read_jobs(connection)]
    matches.sort(key=lambda item: (not item['dealbreakers_passed'], -item['total_score'], item['job_id']))
    return matches
