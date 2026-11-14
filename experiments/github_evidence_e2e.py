"""Synthetic end-to-end verification; a real loopback model must already be running.

Default: mocked GitHub REST transport, real fetcher/parser/matcher/model HTTP.
Run: TALENTMATCH_EMBED_URL=http://127.0.0.1:8080/embed \
     backend/.venv/bin/python experiments/github_evidence_e2e.py
Live GitHub requires BOTH --live-github and --repository pointing to an approved,
public synthetic repository. No cloning, code execution, installation or app DB access.
--require-network-none verifies only loopback is active and outbound TCP is denied.
Only counts, checks, timings, skill names/IDs and source paths are printed.
"""
import argparse
from contextlib import ExitStack, closing
import errno
import hashlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import database, test_github_fetcher as fixtures
from backend.evidence import github_fetcher as fetcher, embedding_client as embeddings
from backend.evidence.github_pipeline import analyze_github_material
from backend.evidence.github_validator import validate_github_repository_url
from backend.matching_engine import calculate_match
from backend.seed_data import SKILLS


def mock_routes(repo):
    base = f"/repos/{repo['owner']}/{repo['repository']}"
    routes, entries = {base: fixtures.Response(fixtures.metadata(repo))}, []
    files = [('README.md', b'Synthetic REST APIs using Python and FastAPI, automated tests, React and TypeScript.'),
             ('package.json', b'{"dependencies":{"react":"1","typescript":"1"}}'),
             ('requirements.txt', b'fastapi>=0.115,<1\n'),
             ('pyproject.toml', b'[project]\ndependencies=["fastapi>=0.115"]\n'),
             ('Dockerfile', b'FROM scratch\n# Synthetic metadata only, never built\n'),
             ('src/main.py', b'# Synthetic source metadata; never execute this file.\n')]
    for path, content in files:
        entry, blob = fixtures.entry(path, content)
        entries.append(entry)
        routes[base + '/git/blobs/' + entry['sha']] = fixtures.Response(blob)
    routes[base + '/git/trees/main?recursive=1'] = fixtures.Response({'sha': 'a'*40, 'truncated': False, 'tree': entries})
    return routes


def prepare(connection, url):
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    connection.executescript(database.SCHEMA_PATH.read_text())
    connection.executemany('INSERT INTO skills VALUES(?,?,?,?)',
        [(i, f'urn:synthetic:skill:{i}', name, category) for i, (name, category) in enumerate(SKILLS, 1)])
    connection.execute('INSERT INTO candidates(id,anonymous_code,full_name,email,has_cv,has_portfolio,languages,needs_visa_sponsorship,skills) VALUES(402,?,?,?,?,?,?,?,?)',
        ('SYNTHETIC-402', 'Synthetic Test Candidate', 'synthetic@example.invalid', 0, 0,
         '{"English":"B2"}', 0, '[{"skill_id":1,"evidence_tier":"self_declared"}]'))
    # Explicit columns keep fixture values independent of application initializers.
    for i, skill in ((1, 1), (2, 3)):
        required, optional = json.dumps([{'skill_id': skill, 'weight': 70}]), json.dumps([{'skill_id': 5, 'weight': 20}])
        connection.execute('INSERT INTO companies(id,name,industry,booth_number,relocation_support,working_language,min_match_threshold,must_have_skills,nice_to_have_skills) VALUES(?,?,?,?,?,?,?,?,?)',
            (i, f'Synthetic Company {i}', 'IT', f'S{i}', 1, 'English', 50, required, optional))
        connection.execute('INSERT INTO job_openings VALUES(?,?,?,?,?,?,?,1)',
            (1000+i, i, f'Synthetic Job {i}', 'it', 'Synthetic fixture.', required, optional))
    connection.execute('INSERT INTO profile_materials(id,candidate_id,category,title,description,url) VALUES(7,402,?,?,?,?)',
        ('github', 'Synthetic API project', 'Synthetic Python and FastAPI REST APIs with automated tests.', url))
    connection.commit()
    connection.execute('PRAGMA query_only=ON')
    return connection.execute('SELECT * FROM profile_materials WHERE id=7 AND candidate_id=402').fetchone()


def state(connection):
    digest = hashlib.sha256('\n'.join(connection.iterdump()).encode()).hexdigest()
    candidate = dict(connection.execute('SELECT * FROM candidates WHERE id=402').fetchone())
    for key in ('languages', 'skills'):
        candidate[key] = json.loads(candidate[key])
    names = {r['id']: r['name'] for r in connection.execute('SELECT id,name FROM skills')}
    scores = {}
    for row in connection.execute('SELECT j.*,c.relocation_support,c.working_language FROM job_openings j JOIN companies c ON c.id=j.company_id'):
        job = dict(row)
        for key in ('must_have_skills', 'nice_to_have_skills'):
            job[key] = json.loads(job[key])
        scores[job['id']] = calculate_match(candidate, job, skill_names=names)
    ranking = sorted(scores, key=lambda identifier: (-scores[identifier]['total_score'], identifier))
    return digest, candidate['skills'], scores, ranking


def verify(report, row, captured, catalog):
    def review_flags(value):
        if isinstance(value, dict):
            if 'review_status' in value:
                assert value['review_status'] == 'unreviewed'
            for child in value.values():
                review_flags(child)
        elif isinstance(value, list):
            for child in value:
                review_flags(child)
    review_flags(report)
    assert report['review_status'] == 'unreviewed' and report['untrusted'] is True
    assert len(report['materials']) == 1
    item = report['materials'][0]
    assert (item['candidate_id'], item['material_id']) == (402, 7)
    assert item['review_status'] == 'unreviewed' and item['untrusted'] is True
    files = {file['path']: file for file in captured[0]['files']}
    assert len(files) <= fetcher.MAX_FILES
    assert all(file['decoded_bytes'] <= fetcher.MAX_FILE_BYTES for file in files.values())
    assert sum(file['decoded_bytes'] for file in files.values()) <= fetcher.MAX_TEXT_BYTES
    assert len(item['semantic_fragments']) <= 6 and len(item['observations']) <= 48
    examples, counts = [], {'file_associations': 0, 'material_metadata_associations': 0}

    def association(value, semantic=False):
        assert catalog[value['skill_id']] == value['skill_name']
        assert value['review_status'] == 'unreviewed'
        source = value['source']
        assert (source['candidate_id'], source['material_id']) == (402, 7)
        assert source['repository'] == item['repository'] and source['untrusted'] is True
        if source['origin'] == 'repository_file':
            file = files[source['file_path']]
            base = f"https://api.github.com/repos/{item['repository']['owner']}/{item['repository']['repository']}/git/blobs/"
            assert source['tree_sha'] == item['tree_sha']
            assert source['blob_sha'] == file['blob_sha'] and re.fullmatch('[0-9a-f]{40}', source['blob_sha'])
            assert source['source_reference'] == file['source_reference'] == base + file['blob_sha']
            counts['file_associations'] += 1
            if len(examples) < 6:
                examples.append({'kind': 'semantic' if semantic else 'observation', 'skill_id': value['skill_id'],
                    'skill_name': value['skill_name'], 'source_path': file['path'],
                    **({'similarity': round(value['similarity_score'], 4)} if semantic else {})})
            text = file['text']
        else:
            assert source['origin'] == 'material_metadata' and source['field'] in ('title', 'description')
            assert all(source[key] is None for key in ('file_path', 'blob_sha', 'source_reference', 'tree_sha'))
            counts['material_metadata_associations'] += 1
            text = row[source['field']]
        if semantic:
            assert value['interpretation'] == 'semantic_relevance_only'
            assert -1 <= value['similarity_score'] <= 1
            assert value['supporting_excerpt'] == text[value['excerpt_start']:value['excerpt_end']]
        else:
            assert 'similarity_score' not in value and value['interpretation'] == 'observation_not_proficiency'

    for fragment in item['semantic_fragments']:
        for value in fragment['matches']:
            association(value, semantic=True)
    for observation in item['observations']:
        assert observation['review_status'] == 'unreviewed'
        assert observation['evidence_kind'] == 'deterministic_observation' and 'similarity_score' not in observation
        for value in observation['skill_associations']:
            association(value)
    return {'retrieved_files': len(files), 'analyzed_fragments': len(item['semantic_fragments']),
            'observations': len(item['observations']), **counts, 'examples': examples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-github', action='store_true', help='Explicitly permit approved public GitHub API retrieval.')
    parser.add_argument('--repository', help='Reviewed public synthetic repository URL; requires --live-github.')
    parser.add_argument('--require-network-none', action='store_true')
    args = parser.parse_args()
    if bool(args.repository) != args.live_github or (args.live_github and args.require_network_none):
        parser.error('Live mode requires both --live-github and --repository, and cannot require network=none.')
    repo = validate_github_repository_url(args.repository or 'https://github.com/RecruitiFiSynthetic/evidence-fixture')
    client = embeddings.EmbeddingClient()  # Validates trusted environment, not a CLI endpoint URL.
    allowed_model = {(client.host, client.port)}
    api_addresses, api_paths, model_calls, captured, replies = set(), [], [], [], {}
    original_connect, original_dns = socket.socket.connect, socket.getaddrinfo
    original_factory, original_json, original_fetch = fetcher._open_connection, fetcher._json_request, fetcher._fetch_repository
    original_model = embeddings.EmbeddingClient._request
    base = f"/repos/{repo['owner']}/{repo['repository']}"
    approved = re.compile(re.escape(base) + r'(?:/git/trees/[^?]+\?recursive=1|/git/blobs/[0-9a-f]{40})?')

    def dns(host, port, *a, **kw):
        assert args.live_github and host == 'api.github.com' and port == 443
        result = original_dns(host, port, *a, **kw)
        api_addresses.update(address[4][0] for address in result if ipaddress.ip_address(address[4][0]).is_global)
        return result

    def connect(sock, address):
        target = (address[0], address[1])
        assert target in allowed_model or (args.live_github and target[1] == 443 and target[0] in api_addresses)
        return original_connect(sock, address)

    def factory(timeout, routes=None):
        connection = original_factory(timeout) if routes is None else fixtures.Connection(routes, [])
        if routes is None:
            assert connection.host == 'api.github.com' and connection.port == 443
            assert connection.tls_context.check_hostname
        request = connection.request
        def audited(method, path, *a, **kw):
            assert method == 'GET' and approved.fullmatch(path)
            api_paths.append(path)
            return request(method, path, *a, **kw)
        connection.request = audited
        return connection

    def record_json(path, limit, budget):
        value = original_json(path, limit, budget)
        replies[path] = value  # Memory-only validated replay for the unavailable-service test.
        return value

    def record_fetch(repository, budget):
        value = original_fetch(repository, budget)
        captured.append(value)
        return value

    def model_request(self, method, path, body, deadline):
        assert (self.host, self.port) in allowed_model and path in ('/readyz', '/embed')
        if body is not None:
            assert len(body) <= embeddings.MAX_REQUEST_BYTES and 1 <= len(json.loads(body)) <= 3
        model_calls.append(path)
        return original_model(self, method, path, body, deadline)

    if args.require_network_none:
        active = {path.name for path in Path('/sys/class/net').iterdir()
                  if path.is_dir() and int((path/'flags').read_text(), 16) & 1}
        assert active == {'lo'}  # Inactive kernel tunnel devices do not provide connectivity.
        with closing(socket.socket()) as probe:
            probe.settimeout(1)
            try:
                original_connect(probe, ('1.1.1.1', 443))
            except OSError as error:
                assert error.errno in (errno.ENETUNREACH, errno.EACCES, errno.EPERM)
            else:
                raise AssertionError('External networking unexpectedly available')
    with closing(sqlite3.connect(':memory:')) as connection, ExitStack() as stack:
        row = prepare(connection, repo['canonical_url'])
        before = state(connection)
        catalog = {r['id']: r['name'] for r in connection.execute('SELECT id,name FROM skills')}
        stack.enter_context(patch.object(sqlite3, 'connect', side_effect=AssertionError('Additional database access forbidden')))
        stack.enter_context(patch.object(socket, 'getaddrinfo', side_effect=dns))
        stack.enter_context(patch.object(socket.socket, 'connect', new=connect))
        stack.enter_context(patch.object(embeddings.EmbeddingClient, '_request', new=model_request))
        stack.enter_context(patch.object(fetcher, '_json_request', side_effect=record_json))
        stack.enter_context(patch.object(fetcher, '_fetch_repository', side_effect=record_fetch))
        stack.enter_context(patch.object(logging.Logger, '_log', side_effect=AssertionError('Unexpected logging during evidence test')))
        stack.enter_context(patch('http.client.HTTPConnection.debuglevel', 0))
        stack.enter_context(patch('subprocess.Popen', side_effect=AssertionError('Code execution forbidden')))
        stack.enter_context(patch('os.system', side_effect=AssertionError('Code execution forbidden')))
        stack.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('Arbitrary URL fetching forbidden')))
        routes = None if args.live_github else mock_routes(repo)
        with patch.object(fetcher, '_open_connection', side_effect=lambda timeout: factory(timeout, routes)):
            started = time.perf_counter()
            report = analyze_github_material(row, connection=connection, synthetic_data=True)
            elapsed = time.perf_counter() - started
        assert report['status'] == 'complete' and report['semantic_status'] == 'complete'
        summary = verify(report, row, captured, catalog)
        assert state(connection) == before
        success_api_count, success_model_count = len(api_paths), len(model_calls)
        assert success_api_count <= fetcher.MAX_REQUESTS and success_model_count <= 37
        # Reserve an unlistened loopback port: actual connection rejection, no mock model errors.
        with closing(socket.socket()) as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            port = unavailable.getsockname()[1]
            allowed_model.add(('127.0.0.1', port))
            replay = {path: fixtures.Response(value) for path, value in replies.items()}
            with patch.dict(os.environ, TALENTMATCH_EMBED_URL=f'http://127.0.0.1:{port}/embed'), \
                 patch.object(fetcher, '_open_connection', side_effect=lambda timeout: factory(timeout, replay)):
                started = time.perf_counter()
                failed = analyze_github_material(row, connection=connection, synthetic_data=True)
                unavailable_seconds = time.perf_counter() - started
        assert failed['semantic_status'] == 'failed' and failed['status'] == 'partial'
        # A bound, unlistened port can time out rather than refuse on macOS.
        # Either must fail closed without fabricated semantic findings.
        assert any(e['stage'] == 'embedding' and e['code'] in ('unavailable', 'timeout') for e in failed['errors'])
        assert failed['materials'][0]['observations'] and not failed['materials'][0]['semantic_fragments']
        assert state(connection) == before
        summary.update(status='PASS', live_github=args.live_github, real_local_model=True,
            os_network_none_verified=args.require_network_none, host_architecture=os.uname().machine,
            end_to_end_seconds=round(elapsed, 3), unavailable_seconds=round(unavailable_seconds, 3),
            github_api_requests=success_api_count, model_http_requests=success_model_count,
            model_revision=report['revision'], unavailable_test='PASS (replayed GitHub, real TCP failure)',
            source_ids_and_references='PASS', all_review_statuses_unreviewed=True,
            observations_separate_from_similarity=True, database_and_candidate_skills_unchanged=True,
            matching_scores_and_job_rankings_unchanged=True, traffic_allowlist='PASS', sensitive_logs='none')
        print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # No traceback/exception message: a library failure could contain input text.
        trace = error.__traceback__
        while trace.tb_next is not None:
            trace = trace.tb_next
        print(json.dumps({'status': 'FAIL', 'failure_type': type(error).__name__,
            'location': f'{Path(trace.tb_frame.f_code.co_filename).name}:{trace.tb_lineno}',
            'details': 'Suppressed to avoid evidence logging.'}))
        raise SystemExit(1)
