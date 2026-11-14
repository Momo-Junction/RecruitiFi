"""Opt-in unauthenticated routes for ONE constant fictional project, not uploads.

Existing hosted authentication middleware and protected AI routers are unchanged.
Mock role selection is presentation only; these narrowly scoped results are public.
"""
import math
import time
import uuid

from fastapi import APIRouter, Depends, Request, Response
from ..database import connect
from . import demo_boundary as boundary, jobs, storage
from .api import Identity, JobId, fail
from .embedding_client import MODEL_ID, MODEL_REVISION
from .synthetic_demo import CANDIDATE_ID, PROJECT


def access(candidate_id: Identity, request: Request, response: Response):
    if not boundary.enabled():
        fail(404, 'Public synthetic demo is disabled.')
    if candidate_id != CANDIDATE_ID:
        fail(403, 'Only fictional candidate 900001 is available.')
    if request.url.query:
        fail(422, 'This demo does not accept query options.')
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/ai-demo/candidates/{candidate_id}', dependencies=[Depends(access)])


def approved(connection, material_id=None):
    try:
        return boundary.material(connection, material_id)
    except ValueError:
        fail(403, 'Only the unchanged provisioned fictional project can be analyzed or shared.')


def latest(connection, material_id):
    row = connection.execute(
        'SELECT * FROM evidence_analysis_jobs WHERE candidate_id=? AND material_id=? AND id LIKE ? ORDER BY created_at DESC,id DESC LIMIT 1',
        (CANDIDATE_ID, material_id, boundary.JOB_PREFIX+'%')).fetchone()
    return dict(row) if row else None


def job_view(job):
    state = job['status']
    if state in jobs.ACTIVE and job['lease_deadline'] < time.time():
        state = 'interrupted'
    error = job['error_code']
    return {'id': job['id'], 'candidate_id': CANDIDATE_ID, 'material_id': job['material_id'],
            'status': state, 'error_code': error if error in ('unavailable','model_not_ready','timeout','unauthorized') else 'analysis_failed' if error else None}


def analysis_view(connection, job):
    if job['run_id'] is None:
        return None
    try:
        run = storage.get_analysis(CANDIDATE_ID, job['run_id'], connection=connection)
    except LookupError:
        fail(404, 'Demo result no longer exists.')
    if (run['material_id'] != job['material_id'] or run['analysis_kind'] != 'project'
            or run['model_id'] != MODEL_ID or run['model_revision'] != MODEL_REVISION):
        fail(403, 'Result is outside the fictional demo boundary.')
    fields = {'project_title': PROJECT['title'], 'project_description': PROJECT['description']}
    sources = []
    if len(run['sources']) > 6 or len(run['findings']) > 30:
        fail(403, 'Result is outside the fictional demo limits.')
    for source in run['sources']:
        start, end = source['excerpt_start'], source['excerpt_end']
        text = fields.get(source['evidence_field'])
        if (source['source_type'] != 'project_link' or text is None
                or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or source['excerpt'] != text[start:end]
                or any(source[k] is not None for k in ('repository_url','file_path','tree_sha','blob_sha','source_reference'))):
            fail(403, 'Result contains non-demo evidence.')
        sources.append({'id': source['id'], 'evidence_field': source['evidence_field'],
                        'excerpt': text[start:end], 'file_path': None, 'source_reference': None})
    source_ids = {s['id'] for s in sources}
    findings = []
    for finding in run['findings']:
        skill = connection.execute('SELECT name FROM skills WHERE id=?', (finding['skill_id'],)).fetchone()
        score = finding['similarity_score']
        if (not skill or finding['source_id'] not in source_ids or finding['finding_kind'] != 'semantic'
                or finding['review_status'] != 'unreviewed' or type(score) not in (int,float)
                or not math.isfinite(score) or not -1 <= score <= 1):
            fail(403, 'Result contains non-demo findings.')
        findings.append({'id': finding['id'], 'skill_id': finding['skill_id'], 'skill_name': skill['name'],
                         'source_id': finding['source_id'], 'finding_kind': 'semantic',
                         'similarity_score': score, 'review_status': 'unreviewed'})
    return {'id': run['id'], 'material_id': job['material_id'], 'model_id': MODEL_ID,
            'model_revision': MODEL_REVISION, 'findings': findings, 'sources': sources}


@router.get('/materials/{material_id}')
def capability(candidate_id: Identity, material_id: Identity):
    with connect() as connection:
        approved(connection, material_id)
        job = latest(connection, material_id)
        return {'enabled': True, 'job': job_view(job) if job else None}


async def empty_body(request: Request):
    # No user-supplied text, URLs, paths, skills, grants or inference options.
    async for chunk in request.stream():
        if chunk:
            fail(422, 'This demo accepts no request body.')


@router.post('/materials/{material_id}/analysis', status_code=202)
def trigger(candidate_id: Identity, material_id: Identity, request: Request, _=Depends(empty_body)):
    manager = getattr(request.app.state, 'evidence_jobs', None)
    if manager is None:
        fail(503, 'Demo analysis processing is unavailable.')
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        approved(connection, material_id)
        job = latest(connection, material_id)
        if job and job['status'] in jobs.ACTIVE and job['lease_deadline'] >= time.time():
            return accepted(job)
        if job and job['status'] == 'completed':
            # Constant evidence/model: reuse results instead of unlimited public inference.
            analysis_view(connection, job)
            return accepted(job)
        if job and time.time() < job['lease_deadline']-jobs.JOB_SECONDS-jobs.LEASE_GRACE_SECONDS+30:
            fail(429, 'Demo retry cooldown is active.')
        # Recover only this route's expired jobs; never alter unrelated AI jobs.
        connection.execute("UPDATE evidence_analysis_jobs SET status='interrupted',error_code='worker_interrupted' WHERE candidate_id=? AND id LIKE ? AND status IN ('queued','running') AND lease_deadline<?",
                           (CANDIDATE_ID, boundary.JOB_PREFIX+'%', time.time()))
        if connection.execute("SELECT 1 FROM evidence_analysis_jobs WHERE status IN ('queued','running')").fetchone():
            fail(429, 'Analysis is busy. Try again later.')
        identifier = boundary.JOB_PREFIX+uuid.uuid4().hex[:16]
        connection.execute("INSERT INTO evidence_analysis_jobs(id,candidate_id,material_id,top_k,status,lease_deadline) VALUES(?,?,?,3,'queued',?)",
                           (identifier,CANDIDATE_ID,material_id,time.time()+jobs.JOB_SECONDS+jobs.LEASE_GRACE_SECONDS))
        job = dict(connection.execute('SELECT * FROM evidence_analysis_jobs WHERE id=?', (identifier,)).fetchone())
    try:
        manager.submit(identifier)
    except Exception:
        with connect() as connection:
            connection.execute("UPDATE evidence_analysis_jobs SET status='failed',error_code='supervisor_unavailable' WHERE id=? AND status='queued'",(identifier,))
        fail(503, 'Demo analysis processing is unavailable.')
    return accepted(job)


def accepted(job):
    base = f'/api/ai-demo/candidates/{CANDIDATE_ID}/analysis-jobs/{job["id"]}'
    return {'job_id': job['id'], 'status': job_view(job)['status'], 'status_url': base, 'result_url': base+'/result'}


@router.get('/analysis-jobs/{job_id}/result')
def result(candidate_id: Identity, job_id: JobId, response: Response):
    if not job_id.startswith(boundary.JOB_PREFIX):
        fail(404, 'Public demo job not found.')
    with connect() as connection:
        material = approved(connection)
        row = connection.execute('SELECT * FROM evidence_analysis_jobs WHERE id=? AND candidate_id=? AND material_id=?',
                                 (job_id,CANDIDATE_ID,material['id'])).fetchone()
        if not row:
            fail(404, 'Public demo job not found.')
        job = dict(row); view = job_view(job)
        if view['status'] in jobs.ACTIVE:
            response.status_code = 202
        return {'job': view, 'analysis': analysis_view(connection, job) if view['status'] == 'completed' else None}


@router.get('/employers/{company_id}/findings')
def employer(candidate_id: Identity, company_id: Identity):
    if company_id != 1:
        fail(403, 'Only demo Employer 001 can use this view.')
    with connect() as connection:
        material = approved(connection)
        if not connection.execute('SELECT 1 FROM companies WHERE id=1').fetchone():
            fail(404, 'Demo Employer is unavailable.')
        job = latest(connection, material['id'])
        state = job_view(job)['status'] if job else 'missing'
        analysis = analysis_view(connection, job) if state == 'completed' else None
        return {'candidate_id': CANDIDATE_ID, 'status': 'pending' if state == 'queued' else state,
                'analyses': [analysis] if analysis else []}


@router.get('/analysis-jobs/{job_id}')
def status(candidate_id: Identity, job_id: JobId):
    return result(candidate_id, job_id, Response())['job']
