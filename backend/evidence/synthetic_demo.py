"""Explicit operator provisioning helper; never called at application startup.

The caller must supply an isolated/approved SQLite connection. This module has
no CLI, database path, networking, schema migration, authentication or reseeding.
Preparation/tests use disposable databases only. Existing records are untouched.
"""
import json

from ..demo_accounts import AI_DEMO_ACCOUNT

CANDIDATE_ID = AI_DEMO_ACCOUNT['candidate_id']
EMPLOYER_ID = 1
PROJECT = {
    'category': 'project',
    'title': 'Fabricated AI demo: imaginary task dashboard',
    'description': (
        'Entirely fabricated hackathon evidence, not a real person or project. '
        'The imaginary project describes REST APIs using Python and FastAPI, '
        'a React interface using TypeScript, and a Docker container configuration. '
        'These statements are synthetic test inputs, not verified achievements.'
    ),
    # Existing schema requires a URL or uploaded BLOB. This reserved placeholder
    # avoids documents/external repositories. Project extraction never fetches it.
    'url': 'https://example.invalid/recruitifi-ai-demo/900001',
}


def provision(connection):
    """Insert one fictional candidate/material atomically; reject every ID collision.

    Repeated calls fail without changes. Do not call against Rahti during
    preparation. No INSERT OR REPLACE/UPDATE/DELETE or automatic seed invocation.
    """
    if connection.in_transaction:
        raise ValueError('Provisioning requires a connection with no active transaction.')
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('SELECT 1 FROM candidates WHERE id=?', (CANDIDATE_ID,)).fetchone():
            raise ValueError('Reserved synthetic ID is occupied; refusing to change it.')
        if not connection.execute('SELECT 1 FROM companies WHERE id=?', (EMPLOYER_ID,)).fetchone():
            raise ValueError('Existing demo Employer company is required; no company will be seeded.')
        connection.execute(
            'INSERT INTO candidates(id,anonymous_code,full_name,email,has_cv,has_portfolio,languages,needs_visa_sponsorship,skills) VALUES(?,?,?,?,?,?,?,?,?)',
            (CANDIDATE_ID, 'Synthetic AI Demo #900001', 'Fictional AI Demo Talent 900001',
             'ai-demo-900001@example.invalid', 0, 1, json.dumps({'English':'B2'}), 0, '[]'))
        material = connection.execute(
            'INSERT INTO profile_materials(candidate_id,category,title,description,url) VALUES(?,?,?,?,?)',
            (CANDIDATE_ID, PROJECT['category'], PROJECT['title'], PROJECT['description'], PROJECT['url']))
        return material.lastrowid
