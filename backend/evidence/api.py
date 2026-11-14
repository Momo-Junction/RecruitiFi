"""Operator-only controls for an explicitly declared synthetic dataset."""
import json
import secrets
import time
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..database import connect
from ..demo_accounts import request_account, require_owner
from . import jobs, storage
from .extractor import MAX_INPUT_BYTES
from .github_validator import validate_github_repository_url
from .sessions import session

Identity = Annotated[int, Path(ge=1, le=2**63-1)]
JobId = Annotated[str, Path(pattern='^[0-9a-f]{32}$')]


def fail(status, detail):
    raise HTTPException(status, detail, headers={'Cache-Control': 'no-store', **({'Retry-After': '1'} if status == 429 else {})})


def access(candidate_id: Identity, request: Request, response: Response):
    try:
        token, identities = jobs.configuration()
    except ValueError as error:
        fail(404 if str(error) == 'disabled' else 503, 'Synthetic analysis controls are unavailable.')
    provided = request.headers.getlist('x-recruitifi-ai-token')
    if not (len(provided) == 1 and secrets.compare_digest(provided[0].encode(), token.encode())):
        try:
            _, account = session(request, write=request.method not in ('GET', 'HEAD'))
        except HTTPException as error:
            fail(403, error.detail)
        if account.get('candidate_id') != candidate_id:
            fail(403, 'This analysis belongs to another synthetic candidate.')
    if candidate_id not in identities:
        fail(403, 'Candidate is not approved for synthetic analysis.')
    require_owner(request_account(request), 'talent', candidate_id)
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/candidates/{candidate_id}', dependencies=[Depends(access)])


class Options(BaseModel):
    model_config = ConfigDict(extra='forbid')
    top_k: int = Field(default=3, ge=1, le=5, strict=True)


async def options(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk) > 512:
            fail(413, 'Analysis options exceed 512 bytes.')
        body.extend(chunk)
    if not body:
        return Options()
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        fail(415, 'Use application/json for analysis options.')
    try:
        return Options.model_validate(json.loads(body.decode('utf-8')))
    except (ValueError, UnicodeError, RecursionError, ValidationError):
        fail(422, 'Expected an object containing only top_k, an integer from 1 to 5.')


def recover(connection):
    # Workers have an absolute self-termination alarm before this lease can expire.
    connection.execute("UPDATE evidence_analysis_jobs SET status='interrupted',error_code='worker_interrupted',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE status IN ('queued','running') AND lease_deadline<?", (time.time(),))


def owned(connection, candidate_id, job_id):
    recover(connection)
    row = connection.execute('SELECT * FROM evidence_analysis_jobs WHERE id=? AND candidate_id=?', (job_id, candidate_id)).fetchone()
    if row is None:
        fail(404, 'Analysis job not found for this candidate.')
    return dict(row)


@router.post('/materials/{material_id}/analysis', status_code=202)
def trigger(candidate_id: Identity, material_id: Identity, request: Request, selected: Options = Depends(options)):
    manager = getattr(request.app.state, 'evidence_jobs', None)
    if manager is None:
        fail(503, 'Analysis processing is not available.')
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        recover(connection)
        material = connection.execute('SELECT category,url,filename,content_type,length(content) AS size FROM profile_materials WHERE id=? AND candidate_id=?', (material_id, candidate_id)).fetchone()
        if material is None:
            fail(404, 'Material not found for this candidate.')
        profile_request=request.url.path.startswith('/api/ai-matches/')
        if material['category'] not in (('cv','project','certificate','research','linkedin','github','website') if profile_request else ('project','github')):
            fail(422, 'Only project and GitHub materials support analysis.')
        if material['size'] is not None and material['size'] > MAX_INPUT_BYTES:
            fail(413, 'Material exceeds the 10 MiB analysis limit.')
        if material['category'] == 'github':
            try:
                if profile_request:
                    from .github_validator import validate_github_repository_or_profile_url
                    validate_github_repository_or_profile_url(material['url'])
                else:validate_github_repository_url(material['url'])
            except ValueError:
                fail(422, 'GitHub material must contain a supported repository URL.')
        elif material['url'] is None and not (profile_request and material['content_type'] in ('image/png','image/jpeg')) and (material['content_type'] != 'application/pdf' or not (material['filename'] or '').lower().endswith('.pdf')):
            fail(422, 'Project file analysis supports text-based PDFs only.')
        if connection.execute("SELECT 1 FROM evidence_analysis_jobs WHERE status IN ('queued','running')").fetchone():
            fail(429, 'An analysis is already active. Retry after it finishes.')
        job_id = uuid.uuid4().hex
        connection.execute("INSERT INTO evidence_analysis_jobs(id,candidate_id,material_id,top_k,status,lease_deadline) VALUES(?,?,?,?,'queued',?)",
                           (job_id, candidate_id, material_id, selected.top_k, time.time()+jobs.JOB_SECONDS+jobs.LEASE_GRACE_SECONDS))
    try:
        manager.submit(job_id)
    except Exception:
        with connect() as connection:
            connection.execute("UPDATE evidence_analysis_jobs SET status='failed',error_code='supervisor_unavailable' WHERE id=? AND status='queued'", (job_id,))
        fail(503, 'Analysis processing is not available.')
    base = f'/api/candidates/{candidate_id}/analysis-jobs/{job_id}'
    return {'job_id': job_id, 'status': 'queued', 'status_url': base, 'result_url': base+'/result'}


@router.get('/analysis-jobs/{job_id}')
def status(candidate_id: Identity, job_id: JobId):
    with connect() as connection:
        return owned(connection, candidate_id, job_id)


@router.get('/analysis-jobs/{job_id}/result')
def result(candidate_id: Identity, job_id: JobId, response: Response):
    with connect() as connection:
        job = owned(connection, candidate_id, job_id)
        if job['status'] in jobs.ACTIVE:
            response.status_code = 202
            return {'job': job, 'analysis': None}
        if job['material_id'] is None:
            fail(410, 'The source material was deleted.')
        if job['run_id'] is None:
            return {'job': job, 'analysis': None}
        try:
            analysis = storage.get_analysis(candidate_id, job['run_id'], connection=connection)
        except LookupError:
            fail(404, 'Analysis result no longer exists.')
        return {'job': job, 'analysis': analysis}


@router.get('/materials/{material_id}/analyses')
def history(candidate_id: Identity, material_id: Identity):
    with connect() as connection:
        recover(connection)
        if not connection.execute('SELECT 1 FROM profile_materials WHERE id=? AND candidate_id=?', (material_id, candidate_id)).fetchone():
            fail(404, 'Material not found for this candidate.')
        return {'jobs': [dict(row) for row in connection.execute('SELECT * FROM evidence_analysis_jobs WHERE candidate_id=? AND material_id=? ORDER BY created_at DESC,id DESC LIMIT 50', (candidate_id, material_id))],
                'runs': storage.list_analysis_runs(candidate_id, material_id=material_id, connection=connection)}


@router.delete('/analysis-jobs/{job_id}')
def delete(candidate_id: Identity, job_id: JobId):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        job = owned(connection, candidate_id, job_id)
        if job['status'] in jobs.ACTIVE:
            fail(409, 'Wait for active analysis to finish before deleting results.')
        if job['run_id'] is not None:
            storage.delete_analysis(candidate_id, job['run_id'], connection=connection)
        connection.execute('DELETE FROM evidence_analysis_jobs WHERE id=? AND candidate_id=?', (job_id, candidate_id))
    return {'deleted': True}
