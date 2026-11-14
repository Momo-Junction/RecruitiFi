"""Local-only Docker smoke/persistence test. No CSC access; uses a disposable volume."""
import base64
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

IMAGE = sys.argv[1] if len(sys.argv) > 1 else 'recruitifi:rahti-local'
PREFIX = 'recruitifi-check-' + uuid.uuid4().hex[:10]
VOLUME = PREFIX + '-data'
containers = []
DEMO_PASSWORD = secrets.token_urlsafe(32)
AUTHORIZATION = "Basic " + base64.b64encode(("demo:" + DEMO_PASSWORD).encode()).decode()


def docker(*args, **kwargs):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT, **kwargs).strip()


def request(base, path, body=None, method=None, authorization=None):
    headers = {'Authorization': authorization} if authorization else {}
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read(), response.headers


def start(suffix, uid, hosted=False, public=False):
    name = PREFIX + suffix
    containers.append(name)
    docker('run', '-d', '--name', name, '--platform', 'linux/amd64',
           '--user', f'{uid}:0', '--read-only', '--cap-drop=ALL',
           '--security-opt=no-new-privileges',
           '--tmpfs', f'/tmp:rw,noexec,nosuid,size=64m,mode=1770,uid={uid},gid=0',
           '--mount', f'type=volume,src={VOLUME},dst=/var/data',
           '-p', '127.0.0.1::8080', '-e', f'TALENTMATCH_HOSTED_DEMO={int(hosted)}',
           '-e', f'TALENTMATCH_DEMO_AUTH_ENABLED={str(not public).lower()}',
           *(['-e', 'TALENTMATCH_DEMO_PASSWORD'] if hosted and not public else []), IMAGE,
           env={**os.environ, 'TALENTMATCH_DEMO_PASSWORD': DEMO_PASSWORD})
    port = docker('port', name, '8080/tcp').rsplit(':', 1)[1]
    base = 'http://127.0.0.1:' + port
    for _ in range(90):
        try:
            data, _ = request(base, '/healthz')
            assert json.loads(data) == {'status': 'ok'}
            return name, base
        except (OSError, urllib.error.URLError):
            if docker('inspect', '-f', '{{.State.Running}}', name) != 'true':
                raise RuntimeError(docker('logs', name))
            time.sleep(1)
    raise RuntimeError('Timed out waiting for healthz: ' + docker('logs', name))


try:
    arch = json.loads(docker('image', 'inspect', IMAGE))[0]
    assert arch['Architecture'] == 'amd64' and arch['Os'] == 'linux'
    assert arch['Config'].get('User', '') == '', 'Image must leave identity to OpenShift.'
    docker('volume', 'create', VOLUME)
    name, base = start('-first', 1000620000)
    html, _ = request(base, '/')
    assert b'<div id="root">' in html
    import re
    script = re.search(rb'<script[^>]+src="([^"]+)"', html).group(1).decode()
    javascript, _ = request(base, script)
    assert b'127.0.0.1:8000' not in javascript and b'localhost:8000' not in javascript
    assert docker('exec', name, 'python', '-c', 'import os; print(os.environ["TALENTMATCH_SERVE_FRONTEND"])') == '1'
    for path in ['/talent', '/employer', '/organizer']:
        assert b'<div id="root">' in request(base, path)[0]
    for path in ['/api/not-a-real-endpoint', '/assets/missing.js', '/unknown-route']:
        try:
            request(base, path)
        except urllib.error.HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError('Unexpected React fallback for ' + path)
    assert json.loads(request(base, '/api/companies')[0]) == [], 'Startup must not seed.'
    assert docker('exec', name, 'python', '-c', 'import os; print(os.getuid())') == '1000620000'
    docker('exec', name, 'python', '-m', 'backend.seed')  # only the new, isolated test DB
    docker('exec', name, 'python', '-c', 'from backend.database import connect; c=connect(); db=c.__enter__(); assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0]=="wal"; c.__exit__(None,None,None)')
    candidates = json.loads(request(base, '/api/candidates')[0])
    candidate_id = candidates[0]['id']
    query = urllib.parse.urlencode({'category': 'cv', 'title': 'Synthetic deployment test', 'filename': 'synthetic.pdf'})
    document = b'%PDF-1.4\nSynthetic deployment test only\n%%EOF\n'
    saved = json.loads(request(base, f'/api/candidates/{candidate_id}/documents?{query}', document, 'POST')[0])
    material_id = saved['materials'][0]['id']
    download = f'/api/candidates/{candidate_id}/documents/{material_id}'
    assert request(base, download)[0] == document
    docker('exec', name, 'python', '-c', 'from backend.database import DB_PATH; assert str(DB_PATH) == "/var/data/talentmatch.sqlite3"; assert DB_PATH.is_file()')
    for actor in ['talent', 'employer']:
        req = urllib.request.Request(base + '/api/swipes', data=json.dumps({'candidate_id': candidate_id, 'company_id': 1, 'actor': actor, 'decision': 'like'}).encode(), method='PUT', headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            result = json.load(response)
            assert result['mutual_match'] == (actor == 'employer')
    inbox_path = f'/api/notifications/talent/{candidate_id}'
    inbox = json.loads(request(base, inbox_path)[0])
    assert len(inbox['entries']) == 1 and inbox['entries'][0]['kind'] == 'match'
    notification_id = inbox['entries'][0]['id']
    assert json.loads(request(base, inbox_path + f'/{notification_id}/read', method='PUT')[0])['unread_count'] == 0
    docker('stop', '--time', '40', name)
    assert docker('inspect', '-f', '{{.State.ExitCode}}', name) == '0'
    name, base = start('-second', 1000620001)
    restored_inbox = json.loads(request(base, inbox_path)[0])
    assert restored_inbox['entries'][0]['id'] == notification_id and restored_inbox['unread_count'] == 0
    assert json.loads(request(base, '/api/notifications/employer/1')[0])['unread_count'] == 1
    assert request(base, download)[0] == document
    assert len(json.loads(request(base, '/api/candidates')[0])) == len(candidates)
    # Write after UID change: test group permissions, not just read persistence.
    req = urllib.request.Request(base + f'/api/candidates/{candidate_id}/skills', data=b'[]', method='PUT', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        assert response.status == 200
    docker('exec', name, 'python', '-c', 'import os,sqlite3,tempfile; src=sqlite3.connect("file:"+os.environ["TALENTMATCH_DB"]+"?mode=ro",uri=True); f=tempfile.NamedTemporaryFile(); dst=sqlite3.connect(f.name); src.backup(dst); assert dst.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; assert dst.execute("SELECT content FROM profile_materials WHERE content IS NOT NULL").fetchone()[0].startswith(b"%PDF-"); restored=sqlite3.connect(":memory:"); dst.backup(restored); assert restored.execute("SELECT count(*) FROM profile_materials").fetchone()[0]>0; restored.close(); dst.close(); src.close(); f.close()')
    docker('stop', '--time', '40', name)
    # Reuse the same synthetic event in hosted mode: authentication must protect
    # frontend, assets, APIs, documentation and persisted document downloads.
    name, base = start('-hosted', 1000620002, hosted=True)
    for path in ['/', '/talent', '/employer', '/organizer', script, '/api/companies', '/api/candidates', download, inbox_path, '/docs', '/openapi.json']:
        for header in [None, 'Basic !!!', 'Basic ' + base64.b64encode(('demo:' + secrets.token_urlsafe(24)).encode()).decode(),
                       'Basic ' + base64.b64encode(('other:' + DEMO_PASSWORD).encode()).decode()]:
            try:
                request(base, path, authorization=header)
            except urllib.error.HTTPError as error:
                assert error.code == 401
                assert error.headers['WWW-Authenticate'].startswith('Basic ')
            else:
                raise AssertionError('Hosted resource accepted missing/invalid credentials: ' + path)
        _, headers = request(base, path, authorization=AUTHORIZATION)
        assert headers['Cache-Control'] == 'no-store'
    assert request(base, download, authorization=AUTHORIZATION)[0] == document
    assert b'<div id="root">' in request(base, '/', authorization=AUTHORIZATION)[0]
    assert len(json.loads(request(base, '/api/candidates', authorization=AUTHORIZATION)[0])) == len(candidates)
    assert json.loads(request(base, '/healthz')[0]) == {'status': 'ok'}
    # Actual hosted upload: unauthorized body must not reach document storage.
    upload = f'/api/candidates/{candidate_id}/documents?{query}'
    try:
        request(base, upload, document, 'POST')
    except urllib.error.HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError('Unauthenticated hosted upload was accepted')
    hosted_saved = json.loads(request(base, upload, document, 'POST', AUTHORIZATION)[0])
    hosted_document_id = hosted_saved['materials'][0]['id']
    docker('stop', '--time', '40', name)
    assert docker('inspect', '-f', '{{.State.ExitCode}}', name) == '0'
    name, base = start('-hosted-recreated', 1000620003, hosted=True)
    assert request(base, f'/api/candidates/{candidate_id}/documents/{hosted_document_id}', authorization=AUTHORIZATION)[0] == document
    assert request(base, download, authorization=AUTHORIZATION)[0] == document
    docker('stop', '--time', '40', name)
    assert docker('inspect', '-f', '{{.State.ExitCode}}', name) == '0'
    name, base = start('-public', 1000620004, hosted=True, public=True)
    assert b'<div id="root">' in request(base, '/')[0]
    assert request(base, download)[0] == document
    assert len(json.loads(request(base, '/api/candidates')[0])) == len(candidates)
    public_request = urllib.request.Request(base + f'/api/candidates/{candidate_id}/skills', data=b'[]', method='PUT', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(public_request) as response:
        assert response.status == 200
    docker('stop', '--time', '40', name)
    for suffix, env_args, expected in [
        ('-no-password', [], 'TALENTMATCH_DEMO_PASSWORD is required'),
        ('-blank-password', ['-e', 'TALENTMATCH_DEMO_PASSWORD=   '], 'TALENTMATCH_DEMO_PASSWORD is required'),
        ('-root', [], 'non-root UID'),
    ]:
        test_name = PREFIX + suffix
        containers.append(test_name)
        result = subprocess.run(['docker', 'run', '--name', test_name, '--platform', 'linux/amd64',
                                 *([] if suffix == '-root' else ['--user', '1000620000:0']),
                                 '-e', 'TALENTMATCH_HOSTED_DEMO=1', *env_args, IMAGE],
                                env={**os.environ, 'TALENTMATCH_DEMO_PASSWORD': secrets.token_urlsafe(24)}, capture_output=True, text=True)
        assert result.returncode != 0 and expected in result.stderr, result.stderr
    print('PASS: amd64, arbitrary UIDs, read-only rootfs, health, frontend, API, SQLite location, graceful stop, upload persistence, changed-UID writes, root/password guards, hosted startup, and frontend/API/download authentication.')
    print('NOT VERIFIED: Rahti SCC admission, CSI fsGroup/SELinux, actual PVC and Route. Hosted mode tested locally; no Rahti deployment performed.')
finally:
    for name in containers:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['docker', 'volume', 'rm', VOLUME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
