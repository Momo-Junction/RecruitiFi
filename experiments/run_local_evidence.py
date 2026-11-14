"""Run the existing local API and private model with one verified demo sign-in.

No cloud access, seeding, document analysis, or frontend changes. Credentials live
in a private temporary directory, never in source or frontend environment values.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(tempfile.gettempdir()) / ('recruitifi-local-ai-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12])
TALENT_IDS = (402,406,411,417,423,429,432,438,445,451,458,463,470,476,483,900001)


def configuration():
    STATE.mkdir(mode=0o700, exist_ok=True)
    if STATE.is_symlink() or STATE.stat().st_uid != os.getuid():
        raise RuntimeError('Local credential directory is not owned by this user.')
    STATE.chmod(0o700)
    path = STATE / 'server-config.json'
    if not path.exists():
        accounts = {f'talent-{i:03}': secrets.token_urlsafe(18) for i in range(1,16)}
        accounts.update({'talent-ai-001':secrets.token_urlsafe(18), 'employer-001':secrets.token_urlsafe(18)})
        env = {
            'TALENTMATCH_VERIFIED_DEMO_LOGIN':'1', 'TALENTMATCH_AI_JOB_MATCHING':'1',
            'TALENTMATCH_AI_CONSENTED_MODE':'1', 'TALENTMATCH_AI_SYNTHETIC_DEMO':'0',
            'TALENTMATCH_AI_PUBLIC_DEMO':'0', 'TALENTMATCH_AI_CANDIDATES':','.join(map(str,TALENT_IDS)),
            'TALENTMATCH_AI_DEMO_ACCOUNTS':json.dumps(accounts),
            'TALENTMATCH_AI_EMPLOYER_ACCESS':'{"1":[900001]}',
            'TALENTMATCH_AI_SESSION_SECRET':secrets.token_urlsafe(48),
            'TALENTMATCH_AI_DEMO_TOKEN':secrets.token_urlsafe(48),
            'TALENTMATCH_EMBED_TOKEN':secrets.token_urlsafe(48),
        }
        with open(path,'x', opener=lambda p,f:os.open(p,f,0o600)) as output:
            json.dump(env,output)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise RuntimeError('Local server configuration is not owned by this user.')
    path.chmod(0o600)
    env = json.loads(path.read_text())
    # Recreate the private presenter list from the server-side configuration.
    credentials = STATE / 'account-passwords.txt'
    if credentials.is_symlink():raise RuntimeError('Unsafe credential file.')
    with open(credentials,'w',opener=lambda p,f:os.open(p,f,0o600)) as output:
        output.write('LOCAL DEMO ONLY — not Rahti credentials\n\n')
        for alias,password in json.loads(env['TALENTMATCH_AI_DEMO_ACCOUNTS']).items():
            output.write(f'{alias}: {password}\n')
    credentials.chmod(0o600)
    return env,credentials


def main():
    env,credentials=configuration()
    model_python=ROOT/'experiments/local_model/.venv/bin/python'
    if not model_python.is_file():raise RuntimeError('Existing local-model virtual environment is required.')
    processes=[]
    os.umask(0o077)
    base=os.environ.copy()
    for name in ('TALENTMATCH_PUBLIC_ORIGIN','TALENTMATCH_EMBED_INTERNAL_HOST','TALENTMATCH_SERVE_FRONTEND'):
        base.pop(name,None)
    base.update(env)
    base.update(TALENTMATCH_AI_FETCH_PUBLIC_PROFILES='1',TALENTMATCH_HOSTED_DEMO='0',TALENTMATCH_DB=str(ROOT/'backend/talentmatch.sqlite3'),
                TALENTMATCH_EMBED_URL='http://127.0.0.1:8081/embed',HF_HUB_OFFLINE='1',
                TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    def stop(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        commands=[
            [str(model_python),'-m','uvicorn','experiments.local_model.service.app:app','--host','127.0.0.1','--port','8081','--workers','1','--no-access-log'],
            [sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000','--workers','1','--no-access-log'],
        ]
        for name,command in zip(('model','backend'),commands):
            with (STATE/f'{name}.log').open('a') as log:
                processes.append(subprocess.Popen(command,cwd=ROOT,env=base,stdout=log,stderr=log))
        print('App: http://localhost:5173/\nLocal account passwords: '+str(credentials)+'\nPrivate service logs: '+str(STATE),flush=True)
        while all(p.poll() is None for p in processes):
            try:processes[0].wait(timeout=1)
            except subprocess.TimeoutExpired:pass
        raise RuntimeError('A local service exited; inspect the private service logs above.')
    except KeyboardInterrupt:
        pass
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=30)
            except subprocess.TimeoutExpired:p.kill();p.wait()


if __name__=='__main__':main()
