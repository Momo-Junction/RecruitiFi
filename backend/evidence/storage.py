"""Explicit SQLite persistence for bounded, unreviewed analysis reports.

Use a caller-owned connection from database.connect(); no default DB is opened,
network requests are made, evidence is logged, or candidate skills are promoted.
Transactions remain caller-owned. Only whitelisted metadata/excerpts are saved.
"""
from contextlib import contextmanager
import math
import re
import uuid

from .github_validator import validate_github_repository_url, validate_github_repository_or_profile_url
from .github_fetcher import _safe_path
from .semantic_matching import EXCERPT_CHARACTERS, MAX_FRAGMENTS

_STATES = {'complete', 'limited', 'partial', 'failed', 'no_evidence', 'no_skills'}
_SHA = re.compile('[0-9a-f]{40}')
_PROJECT_TYPES = {'project_link', 'uploaded_pdf', 'uploaded_image', 'unsupported_file'}
_RUN_COLUMNS = ('material_id', 'analysis_kind', 'model_id', 'model_revision', 'status',
                'extraction_status', 'retrieval_status', 'semantic_status', 'error_code', 'coverage_limited')
_SOURCE_COLUMNS = ('source_type', 'evidence_field', 'repository_url', 'file_path', 'tree_sha', 'blob_sha',
                   'source_reference', 'excerpt', 'excerpt_start', 'excerpt_end')


def _id(value):
    if type(value) is not int or value <= 0:
        raise ValueError('IDs must be positive integers.')
    return value


def _text(value, limit, *, optional=False, empty=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or '\x00' in value or len(value) > limit or (not empty and not value.strip()):
        raise ValueError('Invalid or oversized analysis metadata.')
    return value


def _rows(connection, sql, parameters=()):
    cursor = connection.execute(sql, parameters)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


@contextmanager
def _atomic(connection):
    if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise ValueError('Evidence writes require foreign_keys=ON; use database.connect().')
    started = not connection.in_transaction
    if started:
        connection.execute('BEGIN')
    name = 'evidence_' + uuid.uuid4().hex
    connection.execute('SAVEPOINT ' + name)
    try:
        yield
    except BaseException:
        connection.execute('ROLLBACK TO SAVEPOINT ' + name)
        connection.execute('RELEASE SAVEPOINT ' + name)
        if started:
            connection.rollback()
        raise
    else:
        connection.execute('RELEASE SAVEPOINT ' + name)


def _source(material, value, kind, excerpt='', start=None, end=None):
    source = value.get('source')
    source_type = value.get('evidence_source_type', 'github_file')
    field = value.get('evidence_field')
    result = dict.fromkeys(_SOURCE_COLUMNS)
    if kind=='project' and source_type in ('public_github_profile','public_linkedin_profile'):
        if field!='public_profile_text' or type(start) is not int or type(end) is not int or not 0<=start<=end<=20000 or end-start!=len(excerpt):raise ValueError('Invalid public profile attribution.')
        if source_type=='public_github_profile':
            if material['category']!='github' or validate_github_repository_or_profile_url(material['url']) is not None:raise ValueError('Wrong profile source.')
            reference=material['url']
        else:
            from .public_profiles import linkedin_url
            if material['category']!='linkedin':raise ValueError('Wrong profile source.')
            reference=linkedin_url(material['url'])
        result.update(source_type=source_type,evidence_field=field,source_reference=reference,excerpt=_text(excerpt,EXCERPT_CHARACTERS,empty=True),excerpt_start=start,excerpt_end=end)
        return result
    if kind == 'project':
        if source_type not in _PROJECT_TYPES:
            raise ValueError('Invalid project evidence source type.')
        expected = 'project_link' if material['url'] is not None else 'uploaded_pdf' if material['content_type'] == 'application/pdf' and (material['filename'] or '').lower().endswith('.pdf') else 'uploaded_image' if material['content_type'] in ('image/png', 'image/jpeg') else 'unsupported_file'
        if source_type != expected or field not in ('project_title', 'project_description', 'pdf_text'):
            raise ValueError('Evidence does not match its stored project material.')
        if field == 'pdf_text' and source_type != 'uploaded_pdf':
            raise ValueError('PDF evidence requires a PDF material.')
    else:
        if not isinstance(source, dict) or _id(source.get('candidate_id')) != material['candidate_id'] or _id(source.get('material_id')) != material['id']:
            raise ValueError('Source ownership does not match the material.')
        repository = validate_github_repository_url(material['url'])
        if source.get('repository') != repository:
            raise ValueError('Source repository does not match the material.')
        result['repository_url'] = repository['canonical_url']
        field = field or source.get('field')
        if source.get('origin') == 'repository_file':
            path, tree, blob = source.get('file_path'), source.get('tree_sha'), source.get('blob_sha')
            if not _safe_path(path) or not isinstance(tree, str) or not _SHA.fullmatch(tree) or not isinstance(blob, str) or not _SHA.fullmatch(blob):
                raise ValueError('Invalid immutable GitHub source.')
            expected = f"https://api.github.com/repos/{repository['owner']}/{repository['repository']}/git/blobs/{blob}"
            if source.get('source_reference') != expected:
                raise ValueError('Invalid immutable source reference.')
            result.update(file_path=path, tree_sha=tree, blob_sha=blob, source_reference=expected)
            if source_type not in ('github_file', 'github_readme'):
                raise ValueError('Invalid repository evidence source type.')
        elif source.get('origin') == 'material_metadata':
            if source_type != 'github_metadata' or field not in ('title', 'description') or source.get('field') != field:
                raise ValueError('Invalid saved metadata source.')
            if any(source.get(key) is not None for key in ('file_path', 'tree_sha', 'blob_sha', 'source_reference')):
                raise ValueError('Saved metadata cannot claim a blob reference.')
        else:
            raise ValueError('Invalid GitHub source origin.')
    result.update(source_type=_text(source_type, 64), evidence_field=_text(field, 512),
                  excerpt=_text(excerpt, EXCERPT_CHARACTERS, empty=True), excerpt_start=start, excerpt_end=end)
    if start is not None or end is not None:
        if type(start) is not int or type(end) is not int or start < 0 or end > 20_000 or end-start != len(excerpt):
            raise ValueError('Invalid evidence excerpt offsets.')
        metadata_field = {'project_title': 'title', 'project_description': 'description', 'title': 'title', 'description': 'description'}.get(field)
        if metadata_field and not result['file_path'] and excerpt != material[metadata_field][start:end]:
            raise ValueError('Excerpt does not match saved material metadata.')
    elif excerpt:
        raise ValueError('Evidence excerpts require offsets.')
    return result


def _finding(connection, match, kind, material_id, observation=None):
    if match.get('review_status') != 'unreviewed' or _id(match.get('material_id', material_id)) != material_id:
        raise ValueError('Only unreviewed findings for the source material can be saved.')
    skill = _rows(connection, 'SELECT id,name FROM skills WHERE id=?', (_id(match.get('skill_id')),))
    if not skill or skill[0]['name'] != match.get('skill_name'):
        raise ValueError('Finding must reference an existing skill with its stored name.')
    score = match.get('similarity_score') if kind == 'semantic' else None
    if kind == 'semantic' and (type(score) not in (float, int) or not -1 <= score <= 1 or not math.isfinite(score)):
        raise ValueError('Invalid semantic relevance score.')
    if kind == 'observation' and 'similarity_score' in match:
        raise ValueError('Deterministic observations cannot carry similarity scores.')
    interpretation = 'semantic_relevance_only' if kind == 'semantic' else 'observation_not_proficiency'
    if match.get('interpretation') != interpretation or (kind == 'observation' and match.get('basis') != 'exact_catalog_name'):
        raise ValueError('Invalid finding interpretation or basis.')
    return {'skill_id': skill[0]['id'], 'skill_name': _text(skill[0]['name'], 400), 'finding_kind': kind,
            'similarity_score': score, 'observation_kind': _text(observation['kind'], 64) if observation else None,
            'observed_value': _text(observation['observed_value'], 214) if observation else None}


def _normalize(connection, candidate_id, report):
    _id(candidate_id)
    if report.get('review_status', 'unreviewed') != 'unreviewed' or report.get('status') not in _STATES:
        raise ValueError('Invalid analysis status or review status.')
    kind = 'github' if 'materials' in report else 'project'
    items = report.get('materials') if kind == 'github' else [report]
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        raise ValueError('A report must contain one to three materials.')
    errors = report.get('errors', [])
    if not isinstance(errors, list) or len(errors) > 16 or any(not isinstance(error, dict) for error in errors):
        raise ValueError('Invalid analysis errors.')
    runs, seen = [], set()
    fragment_count = observation_count = 0
    for item in items:
        if item.get('review_status', 'unreviewed') != 'unreviewed':
            raise ValueError('Analysis imports must remain unreviewed.')
        identifier = _id(item.get('material_id'))
        if identifier in seen:
            raise ValueError('Duplicate report material.')
        seen.add(identifier)
        materials = _rows(connection, 'SELECT id,candidate_id,category,title,description,url,filename,content_type FROM profile_materials WHERE id=? AND candidate_id=?', (identifier, candidate_id))
        if not materials:
            raise LookupError('Source material not found for this candidate.')
        material = materials[0]
        profile_metadata=kind=='project' and material['category']=='github' and validate_github_repository_or_profile_url(material['url']) is None
        if (not profile_metadata and material['category'] != kind and not (kind=='project' and material['category'] in ('cv','certificate','research','linkedin','website'))) or _id(item.get('candidate_id', candidate_id)) != candidate_id:
            raise ValueError('Analysis kind or owner does not match stored material.')
        if kind == 'github' and item.get('repository') != validate_github_repository_url(material['url']):
            raise ValueError('Report repository does not match stored material.')
        limited = report.get('coverage_limited', False)
        if type(limited) is not bool:
            raise ValueError('Invalid coverage flag.')
        codes = [error.get('code') for error in errors if error.get('material_id', identifier) == identifier]
        error_code = codes[0] if codes else None
        if error_code is not None and (not isinstance(error_code, str) or not re.fullmatch('[a-z_]{1,64}', error_code)):
            raise ValueError('Invalid sanitized error code.')
        run = {'material_id': identifier, 'analysis_kind': kind, 'model_id': _text(report.get('model'), 200),
               'model_revision': _text(report.get('revision'), 128), 'status': report['status'],
               'extraction_status': _text(report.get('extraction_status'), 64, optional=True),
               'retrieval_status': _text(item.get('retrieval_status'), 64, optional=True),
               'semantic_status': _text(report.get('semantic_status'), 64, optional=True),
               'error_code': error_code, 'coverage_limited': int(limited), 'entries': []}
        fragments = item.get('semantic_fragments' if kind == 'github' else 'fragments', [])
        observations = item.get('observations', [])
        if not isinstance(fragments, list) or not isinstance(observations, list):
            raise ValueError('Evidence collections must be lists.')
        if fragments and report.get('semantic_status') in ('failed', 'not_run', 'no_skills', 'no_evidence'):
            raise ValueError('Failed or unperformed comparisons cannot contain semantic findings.')
        if kind == 'github' and (fragments or observations) and item.get('retrieval_status') not in ('retrieved', 'partial_limit_reached'):
            raise ValueError('Failed retrieval cannot support repository findings.')
        fragment_count += len(fragments)
        observation_count += len(observations)
        if fragment_count > MAX_FRAGMENTS or observation_count > 48:
            raise ValueError('Analysis exceeds existing evidence limits.')
        for fragment in fragments:
            matches = fragment['matches']
            if not isinstance(matches, list) or len(matches) > 5:
                raise ValueError('At most five skills per fragment are supported.')
            for match in matches:
                if kind == 'project' and match.get('evidence_field') == 'pdf_text' and report.get('extraction_status') not in ('extracted', 'text_limit_reached'):
                    raise ValueError('Failed PDF extraction cannot support PDF text findings.')
                source = _source(material, match, kind, match['supporting_excerpt'], match['excerpt_start'], match['excerpt_end'])
                run['entries'].append((source, _finding(connection, match, 'semantic', identifier)))
        for observation in observations:
            if observation.get('review_status') != 'unreviewed' or observation.get('kind') not in ('declared_dependency', 'source_extension', 'file_present') or observation.get('evidence_kind') != 'deterministic_observation' or 'similarity_score' in observation:
                raise ValueError('Invalid deterministic observation.')
            associations = observation['skill_associations']
            if not isinstance(associations, list) or len(associations) > 5:
                raise ValueError('At most five associations per observation are supported.')
            for match in associations:
                source = _source(material, match, kind)
                run['entries'].append((source, _finding(connection, match, 'observation', identifier, observation)))
        runs.append(run)
    return runs


def _insert(connection, table, values):
    columns = tuple(values)
    return connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", tuple(values.values())).lastrowid


def _entries(connection, run_id, entries):
    sources = {}
    for source, finding in entries:
        key = tuple(source[column] for column in _SOURCE_COLUMNS)
        if key not in sources:
            sources[key] = _insert(connection, 'evidence_sources', {'run_id': run_id, **source})
        _insert(connection, 'evidence_skill_findings', {'run_id': run_id, 'source_id': sources[key], **finding})


def save_analysis(candidate_id, report, *, connection):
    """Save a project/GitHub report atomically; return one run ID per material."""
    with _atomic(connection):
        identifiers = []
        for run in _normalize(connection, candidate_id, report):
            identifier = _insert(connection, 'evidence_analysis_runs', {key: run[key] for key in _RUN_COLUMNS})
            _entries(connection, identifier, run['entries'])
            identifiers.append(identifier)
    return identifiers


def _owned_run(connection, candidate_id, run_id):
    result = _rows(connection, 'SELECT r.*,m.candidate_id FROM evidence_analysis_runs r JOIN profile_materials m ON m.id=r.material_id WHERE r.id=? AND m.candidate_id=?', (_id(run_id), _id(candidate_id)))
    if not result:
        raise LookupError('Analysis not found for this candidate.')
    return result[0]


def get_analysis(candidate_id, run_id, *, connection):
    result = _owned_run(connection, candidate_id, run_id)
    result['untrusted'] = True
    result['sources'] = _rows(connection, 'SELECT * FROM evidence_sources WHERE run_id=? ORDER BY id', (run_id,))
    for source in result['sources']:
        source['untrusted'] = True
    result['findings'] = _rows(connection, 'SELECT * FROM evidence_skill_findings WHERE run_id=? ORDER BY id', (run_id,))
    for finding in result['findings']:
        finding['interpretation'] = 'semantic_relevance_only' if finding['finding_kind'] == 'semantic' else 'observation_not_proficiency'
    return result


def list_analysis_runs(candidate_id, *, connection, material_id=None, limit=50):
    _id(candidate_id)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100.')
    parameters = [candidate_id]
    where = 'm.candidate_id=?'
    if material_id is not None:
        where += ' AND r.material_id=?'
        parameters.append(_id(material_id))
    return _rows(connection, f'SELECT r.*,m.candidate_id FROM evidence_analysis_runs r JOIN profile_materials m ON m.id=r.material_id WHERE {where} ORDER BY r.id DESC LIMIT ?', (*parameters, limit))


def replace_analysis(candidate_id, run_id, report, *, connection):
    """Replace one owned run atomically, preserving ID/created_at; reset review."""
    with _atomic(connection):
        old = _owned_run(connection, candidate_id, run_id)
        runs = _normalize(connection, candidate_id, report)
        if len(runs) != 1 or runs[0]['material_id'] != old['material_id']:
            raise ValueError('Replacement must concern the same single material.')
        run = runs[0]
        connection.execute('DELETE FROM evidence_sources WHERE run_id=?', (run_id,))
        assignments = ','.join(key + '=?' for key in _RUN_COLUMNS)
        connection.execute(f"UPDATE evidence_analysis_runs SET {assignments},review_status='unreviewed',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (*[run[key] for key in _RUN_COLUMNS], run_id))
        _entries(connection, run_id, run['entries'])
    return run_id


def delete_analysis(candidate_id, run_id, *, connection):
    with _atomic(connection):
        _owned_run(connection, candidate_id, run_id)
        connection.execute('DELETE FROM evidence_analysis_runs WHERE id=?', (run_id,))
