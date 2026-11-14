"""Local-only Docker smoke/persistence test. No CSC access; uses a disposable volume."""
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


def docker(*args, **kwargs):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT, **kwargs).strip()


def request(base, path, body=None, method=None):
    req = urllib.request.Request(base + path, data=body, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read(), response.headers


def start(suffix, uid):
    name = PREFIX + suffix
    containers.append(name)
    docker('run', '-d', '--name', name, '--platform', 'linux/amd64',
           '--user', f'{uid}:0', '--read-only', '--cap-drop=ALL',
           '--security-opt=no-new-privileges',
           '--tmpfs', f'/tmp:rw,noexec,nosuid,size=64m,mode=1770,uid={uid},gid=0',
           '--mount', f'type=volume,src={VOLUME},dst=/var/data',
           '-p', '127.0.0.1::8080', '-e', 'TALENTMATCH_HOSTED_DEMO=0', IMAGE)
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
    assert b'<div id="root">' in request(base, '/')[0]
    assert json.loads(request(base, '/api/companies')[0]) == [], 'Startup must not seed.'
    assert docker('exec', name, 'python', '-c', 'import os; print(os.getuid())') == '1000620000'
    docker('exec', name, 'python', '-m', 'backend.seed')  # only the new, isolated test DB
    candidates = json.loads(request(base, '/api/candidates')[0])
    candidate_id = candidates[0]['id']
    query = urllib.parse.urlencode({'category': 'cv', 'title': 'Synthetic deployment test', 'filename': 'synthetic.pdf'})
    document = b'%PDF-1.4\nSynthetic deployment test only\n%%EOF\n'
    saved = json.loads(request(base, f'/api/candidates/{candidate_id}/documents?{query}', document, 'POST')[0])
    material_id = saved['materials'][0]['id']
    download = f'/api/candidates/{candidate_id}/documents/{material_id}'
    assert request(base, download)[0] == document
    docker('exec', name, 'python', '-c', 'from backend.database import DB_PATH; assert str(DB_PATH) == "/var/data/talentmatch.sqlite3"; assert DB_PATH.is_file()')
    docker('stop', '--time', '40', name)
    assert docker('inspect', '-f', '{{.State.ExitCode}}', name) == '0'
    name, base = start('-second', 1000620001)
    assert request(base, download)[0] == document
    assert len(json.loads(request(base, '/api/candidates')[0])) == len(candidates)
    # Write after UID change: test group permissions, not just read persistence.
    req = urllib.request.Request(base + f'/api/candidates/{candidate_id}/skills', data=b'[]', method='PUT', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        assert response.status == 200
    docker('exec', name, 'python', '-c', 'import os,sqlite3,tempfile; src=sqlite3.connect("file:"+os.environ["TALENTMATCH_DB"]+"?mode=ro",uri=True); f=tempfile.NamedTemporaryFile(); dst=sqlite3.connect(f.name); src.backup(dst); assert dst.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; assert dst.execute("SELECT content FROM profile_materials WHERE content IS NOT NULL").fetchone()[0].startswith(b"%PDF-"); restored=sqlite3.connect(":memory:"); dst.backup(restored); assert restored.execute("SELECT count(*) FROM profile_materials").fetchone()[0]>0; restored.close(); dst.close(); src.close(); f.close()')
    docker('stop', '--time', '40', name)
    for suffix, env_args, expected in [
        ('-no-password', [], 'TALENTMATCH_DEMO_PASSWORD is required'),
        ('-auth-blocked', ['-e', 'TALENTMATCH_DEMO_PASSWORD'], 'authentication is not implemented'),
        ('-root', [], 'non-root UID'),
    ]:
        test_name = PREFIX + suffix
        containers.append(test_name)
        result = subprocess.run(['docker', 'run', '--name', test_name, '--platform', 'linux/amd64',
                                 *([] if suffix == '-root' else ['--user', '1000620000:0']),
                                 '-e', 'TALENTMATCH_HOSTED_DEMO=1', *env_args, IMAGE],
                                env={**os.environ, 'TALENTMATCH_DEMO_PASSWORD': secrets.token_urlsafe(24)}, capture_output=True, text=True)
        assert result.returncode != 0 and expected in result.stderr, result.stderr
    print('PASS: amd64, arbitrary UIDs, read-only rootfs, health, frontend, API, SQLite location, graceful stop, upload persistence, changed-UID writes, root/password/auth guards.')
    print('NOT VERIFIED: Rahti SCC admission, CSI fsGroup/SELinux, actual PVC and Route. Hosted mode intentionally blocked.')
finally:
    for name in containers:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['docker', 'volume', 'rm', VOLUME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
