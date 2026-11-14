"""Synthetic cookie -> background worker -> real loopback model -> Employer audit.

Run with TALENTMATCH_EMBED_URL configured for the isolated local service.
Only a temporary SQLite database is opened. No GitHub traffic is required.
Output contains counts/status only, never evidence, passwords or embeddings.
"""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from backend import database
from backend.test_evidence_storage import seed, snapshot
from backend.evidence import api, employer_api, jobs, sessions
from backend.evidence.embedding_client import EmbeddingClient


async def audit():
    EmbeddingClient()  # Reject anything except the configured numeric loopback path.
    with tempfile.TemporaryDirectory(prefix='recruitifi-audit-synthetic-') as directory, ExitStack() as stack:
        stack.enter_context(patch.object(database, 'DB_PATH', Path(directory)/'synthetic.sqlite3'))
        stack.enter_context(patch.dict(os.environ, {
            'TALENTMATCH_DB': str(database.DB_PATH),
            'TALENTMATCH_AI_SYNTHETIC_DEMO': '1',
            'TALENTMATCH_AI_DEMO_TOKEN': 'synthetic-audit-operator-not-a-real-secret',
            'TALENTMATCH_AI_SESSION_SECRET': 'synthetic-audit-signing-not-a-real-secret',
            'TALENTMATCH_AI_SYNTHETIC_CANDIDATES': '402,403',
            'TALENTMATCH_AI_DEMO_ACCOUNTS': json.dumps({'talent-001':'synthetic-talent-password','employer-001':'synthetic-employer-password'}),
            'TALENTMATCH_AI_EMPLOYER_ACCESS': '{"1":[402]}'
        }))
        with database.connect() as connection:
            seed(connection, database.SCHEMA_PATH.read_text())
            before = snapshot(connection)
        app = FastAPI()
        for router in (api.router, sessions.router, employer_api.router):
            app.include_router(router)
        manager = jobs.AnalysisManager()
        app.state.evidence_jobs = manager

        async def request(method, path, body=None, headers=()):
            messages = []
            payload = json.dumps(body).encode() if body is not None else b''
            async def receive():
                return {'type':'http.request','body':payload,'more_body':False}
            async def send(message):
                messages.append(message)
            await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1',
                'scheme':'https','server':('audit.invalid',443),'client':('127.0.0.1',1),
                'method':method,'path':path,'raw_path':path.encode(),'root_path':'','query_string':b'',
                'headers':[(b'content-type',b'application/json'),*headers]}, receive, send)
            return messages[0]['status'], json.loads(b''.join(m.get('body',b'') for m in messages)), dict(messages[0]['headers'])

        async def login(account, password):
            status, data, headers = await request('POST','/api/evidence-session',{'account':account,'password':password},[(b'origin',b'https://audit.invalid')])
            assert status == 200
            cookie = headers[b'set-cookie']
            assert all(flag in cookie for flag in (b'HttpOnly',b'Secure',b'SameSite=strict'))
            return [(b'cookie',cookie.split(b';')[0]),(b'origin',b'https://audit.invalid'),(b'x-recruitifi-csrf',data['csrf'].encode())]

        try:
            talent = await login('talent-001','synthetic-talent-password')
            path = '/api/candidates/402/materials/701/analysis'
            assert (await request('POST',path,headers=talent[:-1]))[0] == 403
            status, accepted, _ = await request('POST',path,headers=talent)
            assert status == 202
            deadline = time.monotonic()+25
            polls = 0
            while True:
                status, result, _ = await request('GET',accepted['result_url'],headers=talent)
                polls += 1
                assert status in (200,202)
                if status == 200:
                    break
                assert time.monotonic() < deadline
                await asyncio.sleep(.05)
            assert result['job']['status'] == 'completed'
            analysis = result['analysis']
            assert analysis['findings'] and all(f['review_status']=='unreviewed' for f in analysis['findings'])
            assert {f['source_id'] for f in analysis['findings']} <= {s['id'] for s in analysis['sources']}
            employer = await login('employer-001','synthetic-employer-password')
            status, shared, _ = await request('GET','/api/companies/1/candidates/402/evidence-analysis',headers=employer)
            assert status == 200 and shared['status']=='completed'
            assert shared['analyses'][0]['findings'] == analysis['findings']
            assert (await request('GET','/api/companies/1/candidates/403/evidence-analysis',headers=employer))[0] == 403
            assert (await request('GET',accepted['result_url'],headers=employer))[0] == 403
            with database.connect() as connection:
                assert snapshot(connection) == before
            print(json.dumps({'status':'PASS','real_model':True,'real_isolated_worker':True,
                'talent_cookie_csrf_poll_results':'PASS','employer_sharing_isolation':'PASS',
                'existing_records_unchanged':True,'polls':polls,'findings':len(analysis['findings'])}))
        finally:
            await asyncio.to_thread(manager.close)


if __name__ == '__main__':
    asyncio.run(audit())
