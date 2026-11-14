"""Synthetic-only GitHub observations and review-only semantic associations.

No authorship/proficiency claims, code execution, writes, public API or logging.
"""
from collections import deque
import json
from pathlib import PurePosixPath
import re
import threading
import time
import tomllib

from . import github_fetcher, semantic_matching as semantic
from .embedding_client import EmbeddingServiceError, MODEL_ID, MODEL_REVISION
from .github_validator import validate_github_repository_url

ANALYSIS_SECONDS = 120.0
MAX_OBSERVATIONS = 48
MAX_DECLARATIONS_PER_FILE = 32
_SLOT = threading.BoundedSemaphore(1)
_JS_NAME = re.compile(r'(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
_REQUIREMENT = re.compile(
    r'([A-Za-z0-9][A-Za-z0-9._-]{0,127})(?:\[[A-Za-z0-9._-]+(?:\s*,\s*[A-Za-z0-9._-]+)*\])?'
    r'(?:\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+'
    r'(?:\s*,\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+)*)?\s*(?:#.*)?'
)
_LANGUAGE = {'.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript', '.tsx': 'TypeScript'}


def _remaining(deadline):
    if time.monotonic() >= deadline:
        raise EmbeddingServiceError('timeout')


def _material(value):
    row = dict(value)  # Accept the existing sqlite3.Row/public material shape.
    for field in ('id', 'candidate_id'):
        if type(row.get(field)) is not int or row[field] <= 0:
            raise ValueError('Candidate and material IDs must be positive integers.')
    if row.get('category') != 'github' or row.get('content') is not None:
        raise ValueError('Only existing GitHub link materials are supported.')
    for field, limit in (('title', 120), ('description', 1500)):
        if not isinstance(row.get(field), str) or len(row[field]) > limit:
            raise ValueError('Invalid stored GitHub material metadata.')
    return row, validate_github_repository_url(row.get('url'))


def _source(item, file=None, field=None):
    return {'candidate_id': item['candidate_id'], 'material_id': item['material_id'],
            'repository': dict(item['repository']),
            'origin': 'repository_file' if file is not None else 'material_metadata',
            'tree_sha': item['tree_sha'] if file is not None else None,
            'file_path': file['path'] if file is not None else None,
            'blob_sha': file['blob_sha'] if file is not None else None,
            'source_reference': file['source_reference'] if file is not None else None,
            'field': field, 'untrusted': True}


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Ambiguous manifest')
        value[key] = item
    return value


def _requirement(text):
    match = _REQUIREMENT.fullmatch(text.strip())
    return match[1] if match else None  # Deliberately a subset, no URLs/includes/markers.


def _dependencies(file):
    """Bounded declarative parsing only; values/scripts/links are never executed."""
    name = PurePosixPath(file['path']).name.lower()
    text = file['text']
    declarations, unsupported = [], 0
    if name == 'package.json':
        data = json.loads(text, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(data, dict):
            raise ValueError('Invalid manifest')
        for group in ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies'):
            values = data.get(group, {})
            if not isinstance(values, dict) or any(not isinstance(v, str) for v in values.values()):
                raise ValueError('Invalid dependency declarations')
            for package in sorted(values):
                if len(package) > 214 or not _JS_NAME.fullmatch(package):
                    raise ValueError('Invalid package name')
                pointer = '/' + group + '/' + package.replace('~', '~0').replace('/', '~1')
                declarations.append((package, pointer))
    elif name == 'requirements.txt':
        for line, value in enumerate(text.splitlines(), 1):
            package = _requirement(value)
            if package:
                declarations.append((package, f'line:{line}'))
            elif value.strip() and not value.lstrip().startswith('#'):
                unsupported += 1
    elif name == 'pyproject.toml':
        data = tomllib.loads(text)
        project = data.get('project', {})
        if not isinstance(project, dict):
            raise ValueError('Invalid project metadata')
        values = project.get('dependencies', [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError('Invalid project dependencies')
        for index, value in enumerate(values):
            package = _requirement(value)
            if package:
                declarations.append((package, f'project.dependencies[{index}]'))
            else:
                unsupported += 1
    return declarations[:MAX_DECLARATIONS_PER_FILE], len(declarations) > MAX_DECLARATIONS_PER_FILE, unsupported


def _observations(item, catalog, available, deadline):
    observations, limited = [], False
    names = {}
    for skill in catalog:
        names.setdefault(skill['name'].casefold(), []).append(skill)
    for file in item['_files']:
        _remaining(deadline)
        path = PurePosixPath(file['path'])
        values = []
        suffix = path.suffix.lower()
        if suffix in _LANGUAGE:
            values.append(('source_extension', suffix, _LANGUAGE[suffix], 'file_path'))
        elif path.name.lower() == 'dockerfile':
            values.append(('file_present', 'Dockerfile', 'Docker', 'file_path'))
        if path.name.lower() in ('package.json', 'requirements.txt', 'pyproject.toml'):
            try:
                dependencies, capped, unsupported = _dependencies(file)
                limited |= capped
                if unsupported:
                    item['extraction_issues'].append({'path': file['path'], 'code': 'unsupported_requirement', 'count': unsupported})
                values.extend(('declared_dependency', name, name, location) for name, location in dependencies)
            except (ValueError, RecursionError):
                item['extraction_issues'].append({'path': file['path'], 'code': 'invalid_manifest'})
        for kind, value, catalog_name, location in values:
            if len(observations) >= available:
                return observations, True
            source = _source(item, file, location)
            associations = [{'skill_id': skill['id'], 'skill_name': skill['name'],
                             'basis': 'exact_catalog_name', 'source': dict(source),
                             'review_status': 'unreviewed', 'interpretation': 'observation_not_proficiency'}
                            for skill in names.get(catalog_name.casefold(), [])[:5]]
            observations.append({'kind': kind, 'observed_value': value, 'source': source,
                                 'evidence_kind': 'deterministic_observation', 'skill_associations': associations,
                                 'review_status': 'unreviewed', 'interpretation': 'observation_not_proficiency'})
    return observations, limited


def _windows(text, source, field):
    for start in range(0, len(text), semantic.FRAGMENT_CHARACTERS):
        part = text[start:start + semantic.FRAGMENT_CHARACTERS]
        if part.strip():
            yield {'material_id': source['material_id'], 'source_type': 'github_readme' if source['file_path'] else 'github_metadata',
                   'field': field, 'start': start, 'end': start + len(part), 'text': part, 'source': source}


def _round_robin(iterators):
    pending = deque(iterators)
    while pending:
        iterator = pending.popleft()
        value = next(iterator, None)
        if value is not None:
            yield value
            pending.append(iterator)


def analyze_github_materials(materials, *, connection, synthetic_data=False, consent_verified=False, top_k=3, retrieved=None):
    """One synthetic candidate, 1–3 stored GitHub rows, caller-owned SQLite.

    Returns deterministic observations separately from unreviewed semantic scores.
    A single deadline spans retrieval, extraction and all embedding batches.
    """
    if synthetic_data is not True and consent_verified is not True:
        raise ValueError('Only explicitly declared isolated synthetic experiments are enabled.')
    if not isinstance(materials, (list, tuple)) or not 1 <= len(materials) <= github_fetcher.MAX_REPOSITORIES:
        raise ValueError('Pass one to three GitHub materials.')
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError('top_k must be between 1 and 5.')
    validated = [_material(value) for value in materials]
    if (len({r['candidate_id'] for r, _ in validated}) != 1
            or len({r['id'] for r, _ in validated}) != len(validated)
            or len({repo['canonical_url'].casefold() for _, repo in validated}) != len(validated)):
        raise ValueError('Use distinct materials/repositories for one synthetic candidate.')
    if not _SLOT.acquire(blocking=False):
        raise EmbeddingServiceError('busy')
    try:
        deadline = time.monotonic() + ANALYSIS_SECONDS
        catalog = semantic._catalog(connection)
        fetched = github_fetcher.fetch_github_repositories([repo for _, repo in validated], deadline=deadline) if retrieved is None else retrieved
        if len(fetched)!=len(validated) or any(r['repository']!=repo for r,(_,repo) in zip(fetched,validated)):
            raise ValueError('Retrieved evidence does not match the validated repositories.')
        report = {'status': 'complete', 'model': MODEL_ID, 'revision': MODEL_REVISION,
                  'coverage_limited': False, 'untrusted': True, 'review_status': 'unreviewed',
                  'materials': [], 'semantic_status': 'not_run', 'errors': []}
        groups = []
        for (row, repository), retrieved in zip(validated, fetched):
            item = {'candidate_id': row['candidate_id'], 'material_id': row['id'], 'repository': repository,
                    'tree_sha': retrieved['tree_sha'], 'retrieval_status': retrieved['retrieval_status'],
                    'http_status': retrieved['http_status'], 'skipped': retrieved['skipped'],
                    'files': [{k: value for k, value in file.items() if k != 'text'} for file in retrieved['files']],
                    '_files': retrieved['files'], 'observations': [], 'semantic_fragments': [],
                    'extraction_issues': [], 'review_status': 'unreviewed', 'untrusted': True}
            report['materials'].append(item)
            if item['retrieval_status'] not in ('retrieved', 'partial_limit_reached'):
                report['errors'].append({'stage': 'retrieval', 'material_id': row['id'], 'code': item['retrieval_status']})
                continue
            if item['retrieval_status'] == 'partial_limit_reached':
                report['coverage_limited'] = True
            try:
                available = MAX_OBSERVATIONS - sum(len(previous['observations']) for previous in report['materials'])
                item['observations'], limited = _observations(item, catalog, available, deadline)
                report['coverage_limited'] |= limited
                sources = [_windows(file['text'], _source(item, file, 'readme_text'), 'readme_text')
                           for file in item['_files'] if PurePosixPath(file['path']).name.lower() == 'readme.md']
                for field in ('description', 'title'):
                    sources.append(_windows(row[field], _source(item, field=field), field))
                groups.append(_round_robin(sources))
            except EmbeddingServiceError as error:
                report['errors'].append({'stage': 'analysis', 'code': error.code})
                continue
        all_fragments = _round_robin(groups)
        fragments = []
        for part in all_fragments:
            if len(fragments) == semantic.MAX_FRAGMENTS:
                report['coverage_limited'] = True
                break
            fragments.append(part)
        try:
            if fragments:
                _remaining(deadline)
                matches = semantic.match_evidence_fragments(fragments, connection=connection,
                    synthetic_data=synthetic_data, consent_verified=consent_verified, top_k=top_k, deadline=deadline)
                report['semantic_status'] = matches['status']
                by_id = {item['material_id']: item for item in report['materials']}
                for part, matched in zip(fragments, matches['fragments']):
                    matched['source'] = dict(part['source'])
                    by_id[part['material_id']]['semantic_fragments'].append(matched)
        except EmbeddingServiceError as error:
            report['semantic_status'] = 'failed'
            report['errors'].append({'stage': 'embedding', 'code': error.code})
        finally:
            for item in report['materials']:
                del item['_files']  # Full repository text is never returned or stored.
        if time.monotonic() >= deadline and not any(error['code'] == 'timeout' for error in report['errors']):
            report['errors'].append({'stage': 'analysis', 'code': 'timeout'})
        if report['errors'] or any(item['extraction_issues'] for item in report['materials']):
            report['status'] = 'partial' if any(item['observations'] or item['semantic_fragments'] for item in report['materials']) else 'failed'
        elif report['coverage_limited']:
            report['status'] = 'limited'
        return report
    finally:
        _SLOT.release()


def analyze_github_material(material, *, connection, synthetic_data=False, consent_verified=False, top_k=3, retrieved=None):
    return analyze_github_materials([material], connection=connection, synthetic_data=synthetic_data, consent_verified=consent_verified, top_k=top_k, retrieved=retrieved)
