"""Local Docker validation only; creates/removes exclusively its own containers."""
import json
from pathlib import Path
import platform
import os
import secrets
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parent
IMAGE = 'recruitifi:minilm-service'


def docker(*args, check=True, timeout=120):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'Docker command failed: {args[0]} (exit {result.returncode})')
    return result


def main():
    # Forward by environment name only; never record its value in results/commands.
    os.environ['TALENTMATCH_EMBED_TOKEN'] = secrets.token_urlsafe(48)
    out = ROOT / 'results'
    out.mkdir(exist_ok=True)
    containers = []
    image = json.loads(docker('image', 'inspect', IMAGE).stdout)[0]
    info = json.loads(docker('info', '--format', '{{json .}}').stdout)
    results = {'image': IMAGE, 'image_id': image['Id'], 'image_architecture': image['Architecture'],
               'image_content_bytes': image['Size'], 'host': platform.platform(),
               'docker_daemon_architecture': info['Architecture'],
               'emulated': info['Architecture'] not in ('amd64', 'x86_64'), 'commands': []}

    def start(label, *command, env=None):
        name = f'recruitifi-model-service-{label}-{uuid.uuid4().hex[:8]}'
        args = ['run', '-d', '--pull=never', '--name', name, '--platform=linux/amd64',
                '--memory=512m', '--memory-swap=512m', '--cpus=0.5', '--network=none',
                '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
                '--user=1000620000:0', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64',
                '-e', 'TALENTMATCH_EMBED_TOKEN']
        if env:
            args += ['-e', env]
        args += [IMAGE, *command]
        results['commands'].append(['docker', *args])
        docker(*args)
        containers.append(name)
        return name

    def inspect(name):
        return json.loads(docker('inspect', name).stdout)[0]

    def wait(name):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = inspect(name)['State']
            if not state['Running']:
                return state
            time.sleep(1)
        raise TimeoutError('Experimental container exceeded validation deadline')

    def save_logs(name, label):
        logs = docker('logs', name)
        (out / f'{label}.stdout.log').write_text(logs.stdout)
        (out / f'{label}.stderr.log').write_text(logs.stderr)
        return logs.stdout + logs.stderr

    try:
        print('Running full test suite in constrained offline amd64 container', flush=True)
        unit = start('tests', 'python', '-m', 'unittest', 'service.test_service', '-v')
        results['unit_state'] = wait(unit)
        save_logs(unit, 'unit')
        assert results['unit_state']['ExitCode'] == 0 and not results['unit_state']['OOMKilled']
        docker('rm', unit)
        containers.remove(unit)

        print('Starting real loopback HTTP service in fresh constrained container', flush=True)
        started = time.perf_counter()
        server = start('http')
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert inspect(server)['State']['Running'], 'Server exited during startup'
            logs = docker('logs', server)
            if 'Uvicorn running on http://127.0.0.1:8080' in logs.stderr:
                break
            time.sleep(1)
        else:
            raise TimeoutError('Model service did not become ready')
        results['observed_startup_seconds'] = time.perf_counter() - started
        config = inspect(server)['HostConfig']
        results['limits'] = {key: config[key] for key in ('Memory', 'MemorySwap', 'NanoCpus', 'NetworkMode', 'ReadonlyRootfs', 'PortBindings')}
        assert config['Memory'] == config['MemorySwap'] == 536870912
        assert config['NanoCpus'] == 500000000 and config['NetworkMode'] == 'none'
        assert not config['PortBindings']
        assert config['ReadonlyRootfs']
        sockets = docker('exec', server, 'cat', '/proc/net/tcp').stdout
        assert '0100007F:1F90' in sockets and '00000000:1F90' not in sockets
        results['loopback_binding_verified'] = True
        identity = docker('exec', server, 'id', '-u').stdout.strip()
        assert identity == '1000620000'
        results['runtime_uid'] = identity
        dependencies = docker('exec', server, 'cat', '/experiment/installed-requirements.txt').stdout
        (out / 'installed-requirements.txt').write_text(dependencies)
        smoke = docker('exec', server, 'python', '-m', 'service.http_smoke', check=False, timeout=240)
        results['http_smoke_exit_code'] = smoke.returncode
        (out / 'http-smoke.stderr.log').write_text(smoke.stderr)
        assert smoke.returncode == 0, 'HTTP smoke checks failed'
        results['http'] = json.loads(smoke.stdout)
        docker('stop', '-t', '30', server)
        results['server_state'] = inspect(server)['State']
        logs = save_logs(server, 'server')
        assert 'SYNTHETIC_PRIVATE_TEXT_4C_NOT_FOR_LOGGING' not in logs
        assert 'Developed REST APIs using Python and FastAPI.' not in logs
        assert 'embeddings' not in logs.lower()
        assert os.environ['TALENTMATCH_EMBED_TOKEN'] not in logs
        assert not results['server_state']['OOMKilled'] and results['server_state']['ExitCode'] == 0
        results['no_sensitive_server_logging'] = True
        results['model_startup_count'] = logs.count('Application startup complete.')
        assert results['model_startup_count'] == 1
        results['image_size_tree'] = docker('image', 'ls', '--tree', IMAGE).stdout
        print('Testing missing local model startup failure', flush=True)
        missing = start('missing', env='LOCAL_MODEL_DIR=/tmp/missing-model')
        results['missing_model_state'] = wait(missing)
        missing_logs = save_logs(missing, 'missing-model')
        assert results['missing_model_state']['ExitCode'] != 0
        assert not results['missing_model_state']['OOMKilled']
        assert 'Local model initialization failed' in missing_logs
        results['status'] = 'PASS'
    finally:
        for name in containers:
            docker('rm', '-f', name, check=False)
        (out / 'container-checks.json').write_text(json.dumps(results, indent=2) + '\n')
    print('All container checks passed; experimental containers removed.', flush=True)


if __name__ == '__main__':
    main()
