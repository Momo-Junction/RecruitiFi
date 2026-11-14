"""Bounded synthetic-only background processing; no HTTP request runs analysis."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import multiprocessing
import os
from pathlib import Path
import re
import signal
import threading
import time

from .. import database
from . import storage
from .embedding_client import EmbeddingServiceError
from .extractor import extract_project_evidence
from .github_pipeline import analyze_github_material
from .semantic_matching import match_project_evidence
from . import demo_boundary
from .extractor import extract_project_material

JOB_SECONDS = 150.0
LEASE_GRACE_SECONDS = 10.0
MAX_RESULT_BYTES = 1_048_576
ACTIVE = ('queued', 'running')


def configuration():
    """Explicit account allowlist; consented mode also requires per-material approval."""
    consented=os.environ.get('TALENTMATCH_AI_CONSENTED_MODE','0')=='1'
    if not consented and os.environ.get('TALENTMATCH_AI_SYNTHETIC_DEMO', '0') != '1':
        raise ValueError('disabled')
    token = os.environ.get('TALENTMATCH_AI_DEMO_TOKEN', '')
    identities = os.environ.get('TALENTMATCH_AI_CANDIDATES' if consented else 'TALENTMATCH_AI_SYNTHETIC_CANDIDATES', '').split(',')
    if (not 32 <= len(token) <= 256 or any(not 33 <= ord(c) <= 126 for c in token)
            or not 1 <= len(identities) <= 100 or any(not re.fullmatch('[1-9][0-9]{0,18}', value) or int(value) > 2**63-1 for value in identities)):
        raise ValueError('invalid_configuration')
    return token, {int(value) for value in identities}


def allowed(candidate_id):
    if candidate_id == demo_boundary.CANDIDATE_ID and demo_boundary.enabled():
        return True
    try:
        return candidate_id in configuration()[1]
    except ValueError:
        return False


def _load_job(job_id):
    with database.connect() as connection:
        row = connection.execute('SELECT * FROM evidence_analysis_jobs WHERE id=?', (job_id,)).fetchone()
        return dict(row) if row else None


def _analyze_material(job, deadline):
    """Worker adapter; existing pipelines keep their own tighter budgets/limits."""
    if not allowed(job['candidate_id']):
        raise ValueError('Synthetic analysis is no longer enabled.')
    with database.connect() as connection:
        if demo_boundary.public_job(job):
            if not demo_boundary.enabled():
                raise ValueError('Public demo is disabled.')
            material = demo_boundary.material(connection, job['material_id'])
            return match_project_evidence(extract_project_material(material), connection=connection,
                                          synthetic_data=True, top_k=3)
        row = connection.execute('SELECT id,candidate_id,category,title,description,skill_id,url FROM profile_materials WHERE id=? AND candidate_id=?',
                                 (job['material_id'], job['candidate_id'])).fetchone()
        if row is None:
            raise LookupError('Source deleted.')
        if row['category'] == 'github':
            return analyze_github_material(row, connection=connection, synthetic_data=True, top_k=job['top_k'])
        if row['category'] != 'project':
            raise ValueError('Unsupported material.')
        evidence = extract_project_evidence(job['candidate_id'], job['material_id'])
        if time.time() >= deadline:
            raise TimeoutError()
        return match_project_evidence(evidence, connection=connection, synthetic_data=True, top_k=job['top_k'])


def analyze_material(job,deadline):
    from . import profile_matching
    approved=False
    if profile_matching.enabled():
        with database.connect() as c:
            try:approved=job['material_id'] in profile_matching.material_ids(c,job['candidate_id'])
            except (ValueError,TypeError):pass
    if approved:
        with database.connect() as c:
            _,materials,_,_,_=profile_matching.snapshot(c,job['candidate_id'])
            profile_matching.validate_materials(materials)
            usable,_=profile_matching.partition_materials(materials)
            for material in usable:
                if not profile_matching.repository_material(material):profile_matching.extracted(material)
            retrieved=profile_matching.retrieve(materials)
            row=next(m for m in materials if m['id']==job['material_id'])
            consented=os.environ.get('TALENTMATCH_AI_CONSENTED_MODE')=='1' and bool(c.execute('SELECT 1 FROM ai_material_consents WHERE material_id=? AND candidate_id=?',(row['id'],job['candidate_id'])).fetchone())
            public=retrieved.get(row['id'],{})
            report=profile_matching.profile_report(row,public,c,consented) if public.get('public_profile') else None
            if report is None and not profile_matching.repository_material(row):
                report=match_project_evidence(profile_matching.extracted(row),connection=c,synthetic_data=not consented,consent_verified=consented,top_k=3)
            elif report is None:report=analyze_github_material(row,connection=c,synthetic_data=not consented,consent_verified=consented,top_k=3,retrieved=[retrieved[row['id']]])
            report['ai_job_matches']=profile_matching.compute(c,job['candidate_id'],retrieved=retrieved)
            return report
    if os.environ.get('TALENTMATCH_AI_CONSENTED_MODE')=='1':
        raise ValueError('Explicit current-material consent is required.')
    return _analyze_material(job,deadline)


def _child(job, path, deadline, sender):
    # The absolute alarm also stops orphaned workers if the API parent is killed.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline-time.time()))
    database.DB_PATH = Path(path)
    from .profile_matching import AnalysisInputError
    logging.disable(logging.CRITICAL)
    with open(os.devnull, 'w') as sink:
        import contextlib
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            try:
                payload = {'report': analyze_material(job, deadline)}
            except AnalysisInputError as error:
                payload = {'error': error.code}
            except EmbeddingServiceError as error:
                payload = {'error': error.code}
            except LookupError:
                payload = {'error': 'source_deleted'}
            except TimeoutError:
                payload = {'error': 'timeout'}
            except Exception:
                payload = {'error': 'analysis_failed'}
            try:
                body = json.dumps(payload, allow_nan=False).encode()
                if len(body) > MAX_RESULT_BYTES:
                    body = b'{"error":"result_too_large"}'
                sender.send_bytes(body)
            except Exception:
                pass
            finally:
                sender.close()


def execute_isolated(job, path, deadline, cancelled):
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(job, str(path), deadline, sender), daemon=True)
    try:
        process.start()
        sender.close()
        while process.is_alive():
            if cancelled() or time.time() >= deadline:
                return {'error': 'cancelled' if cancelled() else 'timeout'}
            if receiver.poll(0.05):
                return json.loads(receiver.recv_bytes(MAX_RESULT_BYTES).decode())
        if receiver.poll():
            return json.loads(receiver.recv_bytes(MAX_RESULT_BYTES).decode())
        return {'error': 'timeout' if time.time() >= deadline or process.exitcode == -signal.SIGALRM else 'worker_failed'}
    except (EOFError, OSError, ValueError):
        return {'error': 'worker_failed'}
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            process.close()
        receiver.close()
        sender.close()


class AnalysisManager:
    def __init__(self, execute=execute_isolated):
        self.execute = execute
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='synthetic-evidence-supervisor')
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.future = None

    def submit(self, job_id):
        with self.lock:
            if self.stop.is_set() or (self.future is not None and not self.future.done()):
                raise RuntimeError('Supervisor unavailable.')
            self.future = self.executor.submit(self._run, job_id, database.DB_PATH)

    def _run(self, job_id, path):
        job = _load_job(job_id)
        if not job or job['status'] != 'queued':
            return
        deadline = job['lease_deadline'] - LEASE_GRACE_SECONDS

        def cancelled():
            current = _load_job(job_id)
            return self.stop.is_set() or not current or current['status'] not in ACTIVE or current['material_id'] is None or not allowed(current['candidate_id'])

        try:
            with database.connect() as connection:
                connection.execute("UPDATE evidence_analysis_jobs SET status='running',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status='queued'", (job_id,))
            payload = self.execute(job, path, deadline, cancelled)
            with database.connect() as connection:
                connection.execute('BEGIN IMMEDIATE')
                current = connection.execute('SELECT * FROM evidence_analysis_jobs WHERE id=?', (job_id,)).fetchone()
                if current is None or current['status'] not in ACTIVE:
                    return
                error = payload.get('error')
                if time.time() >= deadline:
                    error = 'timeout'
                if self.stop.is_set() or current['material_id'] is None or not allowed(current['candidate_id']):
                    error = 'cancelled'
                run_id = None
                if not error:
                    if demo_boundary.public_job(job):
                        if not demo_boundary.enabled():
                            raise ValueError('Public demo is disabled.')
                        demo_boundary.material(connection, current['material_id'])
                    report = payload['report']
                    ids = storage.save_analysis(current['candidate_id'], report, connection=connection)
                    if len(ids) != 1 or connection.execute('SELECT material_id FROM evidence_analysis_runs WHERE id=?', (ids[0],)).fetchone()[0] != current['material_id']:
                        raise ValueError('Result does not match job material.')
                    run_id = ids[0]
                    if 'ai_job_matches' in report:
                        from . import profile_matching
                        profile_matching.save(connection,current['candidate_id'],run_id,report['ai_job_matches'])
                    if report['status'] in ('partial', 'failed'):
                        error = 'analysis_incomplete'
                if error and not re.fullmatch('[a-z_]{1,64}', error):
                    error = 'analysis_failed'
                status = 'timed_out' if error == 'timeout' else 'cancelled' if error == 'cancelled' else 'failed' if error else 'completed'
                connection.execute("UPDATE evidence_analysis_jobs SET status=?,error_code=?,run_id=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                                   (status, error, run_id, job_id))
        except Exception:
            # No exception strings, document text, repository contents or vectors in logs.
            with database.connect() as connection:
                connection.execute("UPDATE evidence_analysis_jobs SET status='failed',error_code='analysis_failed',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status IN ('queued','running')", (job_id,))

    def close(self):
        self.stop.set()
        self.executor.shutdown(wait=True, cancel_futures=False)
