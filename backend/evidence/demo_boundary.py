"""Immutable public-demo boundary; never read uploaded content or external URLs."""
import os

from .synthetic_demo import CANDIDATE_ID, PROJECT

JOB_PREFIX = '900001a1900001a1'


def enabled():
    return (os.environ.get('TALENTMATCH_AI_PUBLIC_DEMO') == '1'
            and os.environ.get('TALENTMATCH_AI_SYNTHETIC_DEMO') == '1'
            and os.environ.get('TALENTMATCH_AI_SYNTHETIC_CANDIDATES') == str(CANDIDATE_ID))


def public_job(job):
    return job.get('candidate_id') == CANDIDATE_ID and str(job.get('id', '')).startswith(JOB_PREFIX)


def material(connection, material_id=None):
    """Require exact fictional identity and exactly one unchanged fixture project.

    Compare metadata only. Never select BLOBs, arbitrary file paths or link values.
    Returned extraction input is built from source constants, not mutable content.
    """
    candidate = connection.execute(
        'SELECT anonymous_code,full_name,email FROM candidates WHERE id=?', (CANDIDATE_ID,)).fetchone()
    if not candidate or tuple(candidate) != ('Synthetic AI Demo #900001', 'Fictional AI Demo Talent 900001', 'ai-demo-900001@example.invalid'):
        raise ValueError('Fictional demo identity unavailable.')
    rows = connection.execute(
        'SELECT id,category=? AND title=? AND description=? AND url=? AND skill_id IS NULL '
        'AND filename IS NULL AND content_type IS NULL AND content IS NULL AS approved '
        'FROM profile_materials WHERE candidate_id=? LIMIT 2',
        (PROJECT['category'], PROJECT['title'], PROJECT['description'], PROJECT['url'], CANDIDATE_ID)).fetchall()
    if len(rows) != 1 or not rows[0]['approved'] or (material_id is not None and rows[0]['id'] != material_id):
        raise ValueError('Only the unchanged fictional project is available.')
    return {'id': rows[0]['id'], 'candidate_id': CANDIDATE_ID, **PROJECT, 'skill_id': None}
