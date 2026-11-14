"""Run only this experiment's containers, sequentially; retain raw audit evidence."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parent
IMAGE = 'recruitifi:minilm-amd64-int8'


def docker(*args, check=True, timeout=120):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'docker {args}: {result.stderr}')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeats', type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    out = ROOT / 'results-linux-amd64'
    out.mkdir(exist_ok=True)
    image = json.loads(docker('image', 'inspect', IMAGE).stdout)[0]
    info = json.loads(docker('info', '--format', '{{json .}}').stdout)
    metadata = {'host_machine': platform.machine(), 'host_system': platform.system(),
                'daemon_architecture': info['Architecture'], 'daemon_os': info['OSType'],
                'docker_version': info['ServerVersion'],
                'image_architecture': image['Architecture'], 'image_os': image['Os'],
                'image_id': image['Id'], 'image_size_bytes': image['Size'],
                'emulated': info['Architecture'] not in ('x86_64', 'amd64'),
                'warning': 'Apple Silicon emulation; not native Linux/amd64 or Rahti performance.'}
    (out / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')
    results = []
    for repeat in range(1, args.repeats + 1):
        for batch in (1, 3):
            for tokens in (128, 256):
                case = f'b{batch}-t{tokens}-r{repeat}'
                name = f'recruitifi-minilm-{case}-{uuid.uuid4().hex[:8]}'
                command = ['run', '-d', '--name', name, '--platform', 'linux/amd64',
                           '--memory=512m', '--memory-swap=512m', '--cpus=0.5',
                           '--network=none', '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
                           '--user', '1000620000:0', '--cap-drop=ALL', '--security-opt', 'no-new-privileges',
                           '--pids-limit=64', IMAGE, 'python', 'benchmark_amd64.py',
                           '--batch-size', str(batch), '--max-tokens', str(tokens)]
                record = {'case': case, 'command': ['docker', *command]}
                print(f'Starting {case}', flush=True)
                try:
                    created = docker(*command)
                    record['docker_run_exit_code'] = created.returncode
                    deadline = time.monotonic() + 300
                    while True:
                        inspect = json.loads(docker('inspect', name).stdout)[0]
                        if not inspect['State']['Running']:
                            break
                        if time.monotonic() > deadline:
                            record['timeout'] = True
                            docker('stop', '-t', '5', name)
                            inspect = json.loads(docker('inspect', name).stdout)[0]
                            break
                        time.sleep(2)
                    state, config = inspect['State'], inspect['HostConfig']
                    record['state'] = state
                    record['limits'] = {key: config[key] for key in
                                        ('Memory', 'MemorySwap', 'NanoCpus', 'NetworkMode', 'ReadonlyRootfs', 'PidsLimit')}
                    assert config['Memory'] == 536870912
                    assert config['MemorySwap'] == 536870912
                    assert config['NanoCpus'] == 500000000
                    assert config['NetworkMode'] == 'none'
                    logs = docker('logs', name, check=False)
                    (out / f'{case}.stdout.log').write_text(logs.stdout)
                    (out / f'{case}.stderr.log').write_text(logs.stderr)
                    if state['ExitCode'] == 0:
                        record['measurement'] = json.loads(logs.stdout)
                    print(f"Finished {case}: exit={state['ExitCode']}, OOM={state['OOMKilled']}", flush=True)
                except Exception as error:
                    record['error'] = str(error)
                    print(f'Failed {case}: {error}', flush=True)
                finally:
                    docker('rm', '-f', name, check=False)
                (out / f'{case}.json').write_text(json.dumps(record, indent=2) + '\n')
                results.append(record)
                (out / 'summary.json').write_text(json.dumps({'environment': metadata, 'tests': results}, indent=2) + '\n')
    if any('measurement' not in item for item in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
