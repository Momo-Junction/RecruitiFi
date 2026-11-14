"""Password-verified synthetic demo sessions, not production authentication."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import threading
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from ..demo_accounts import BY_ID
from .jobs import configuration

router = APIRouter(prefix='/api/evidence-session')
COOKIE = 'recruitifi_evidence_demo'
_attempts = {}
_lock = threading.Lock()


def employer_grants(approved):
    grants = json.loads(os.environ.get('TALENTMATCH_AI_EMPLOYER_ACCESS', '{}'))
    if not isinstance(grants, dict) or len(grants) > 5:
        raise ValueError()
    for company, candidates in grants.items():
        if not company.isdigit() or not isinstance(candidates, list) or len(candidates) > 15 or any(type(i) is not int or i not in approved for i in candidates):
            raise ValueError()
    return grants


def settings():
    try:
        operator, approved = configuration()
        key = os.environ.get('TALENTMATCH_AI_SESSION_SECRET', '')
        accounts = json.loads(os.environ.get('TALENTMATCH_AI_DEMO_ACCOUNTS', '{}'))
        if len(key) < 32 or not isinstance(accounts, dict) or not 1 <= len(accounts) <= len(BY_ID):
            raise ValueError()
        for identity, password in accounts.items():
            account = BY_ID.get(identity, {})
            permitted = account.get('candidate_id') in approved if account.get('role') == 'talent' else account.get('role') in ('employer','organizer')
            if not permitted or not isinstance(password, str) or not 12 <= len(password) <= 128:
                raise ValueError()
        if len(set(accounts.values())) != len(accounts) or key == operator or any(password in (key, operator) for password in accounts.values()):
            raise ValueError()
        return key.encode(), accounts
    except (ValueError, TypeError):
        raise HTTPException(404, 'Synthetic browser analysis is disabled.') from None


def origin(request):
    expected=expected_origin(request)
    values = request.headers.getlist('origin')
    if len(values) != 1 or values[0] != expected:
        raise HTTPException(403, 'Same-origin request required.')


def expected_origin(request):
    configured=os.environ.get('TALENTMATCH_PUBLIC_ORIGIN','')
    if not configured:return str(request.base_url).rstrip('/')
    parsed=urlsplit(configured)
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or parsed.port not in (None,443) or request.url.hostname!=parsed.hostname):
        raise HTTPException(403,'Invalid application origin configuration.')
    return configured


def session(request, write=False):
    key, _ = settings()
    try:
        value, signature = request.cookies.get(COOKIE, '').split('.')
        expected = hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(value))
        _, accounts = settings()
        account = BY_ID[data['account']]
        if data['expires'] <= time.time() or data['account'] not in accounts:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, 'Sign in to your synthetic demo account.') from None
    if write:
        origin(request)
        tokens = request.headers.getlist('x-recruitifi-csrf')
        if len(tokens) != 1 or not secrets.compare_digest(tokens[0].encode(), data['csrf'].encode()):
            raise HTTPException(403, 'CSRF verification failed.')
    return data, account


@router.get('')
def current(request: Request, response: Response):
    data, account = session(request)
    response.headers['Cache-Control'] = 'no-store'
    return {**{key: account[key] for key in ('role','candidate_id','company_id') if key in account}, 'account_id': data['account'], 'csrf': data['csrf']}


@router.get('/config')
def configuration_status(response: Response):
    """Public capability bit only; never disclose accounts, passwords or secrets."""
    response.headers['Cache-Control'] = 'no-store'
    enabled = os.environ.get('TALENTMATCH_VERIFIED_DEMO_LOGIN', '0') == '1'
    if enabled:
        try:
            settings()
        except HTTPException:
            raise HTTPException(503, 'Verified demo login is not configured.') from None
    return {'verified_login_required': enabled}


@router.post('')
async def login(request: Request, response: Response):
    key, accounts = settings()
    origin(request)
    with _lock:
        peer = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        for address in list(_attempts):
            if now-_attempts[address][0] > 60:
                del _attempts[address]
        since, count = _attempts.get(peer, (now, 0))
        if count >= 10 or (peer not in _attempts and len(_attempts) >= 256):
            raise HTTPException(429, 'Too many demo login attempts.', headers={'Retry-After':'60'})
        _attempts[peer] = (since, count+1)
    body = bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk) > 512:
            raise HTTPException(413, 'Login body too large.')
        body.extend(chunk)
    try:
        supplied = json.loads(body)
        identity, password = supplied['account'], supplied['password']
        expected = accounts.get(identity)
        if not isinstance(password, str) or expected is None or not secrets.compare_digest(password.encode(), expected.encode()):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, 'Invalid synthetic account credentials.') from None
    data = {'account': identity, 'expires': int(time.time())+3600, 'csrf': secrets.token_urlsafe(32)}
    value = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    signed = value+'.'+hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
    secure = expected_origin(request).startswith('https://')
    if not secure and request.url.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise HTTPException(403, 'HTTPS is required.')
    response.set_cookie(COOKIE, signed, max_age=3600, httponly=True, secure=secure, samesite='strict', path='/api')
    response.headers['Cache-Control'] = 'no-store'
    return {**{key: BY_ID[identity][key] for key in ('role','candidate_id','company_id') if key in BY_ID[identity]}, 'csrf': data['csrf']}


@router.delete('')
def logout(request: Request, response: Response):
    session(request, write=True)
    response.delete_cookie(COOKIE, path='/api', httponly=True, samesite='strict')
    return {'signed_out': True}
