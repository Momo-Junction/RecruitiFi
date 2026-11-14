"""Deterministic demo identities, not authentication or secure authorization."""
import re

from fastapi import APIRouter, HTTPException, Request

from .database import connect
from .models import SwipeDecision

# Explicit seed IDs: never pick a different record if a required profile is absent.
TALENT_IDS = (402, 406, 411, 417, 423, 429, 432, 438, 445, 451, 458, 463, 470, 476, 483)
EMPLOYER_IDS = (1, 2, 3, 4, 5)
ACCOUNTS = [
    *[dict(demo_account_id=f'talent-{index:03}', role='talent', candidate_id=identity)
      for index, identity in enumerate(TALENT_IDS, 1)],
    *[dict(demo_account_id=f'employer-{index:03}', role='employer', company_id=identity)
      for index, identity in enumerate(EMPLOYER_IDS, 1)],
    dict(demo_account_id='organizer-001', role='organizer'),
]
BY_ID = {account['demo_account_id']: account for account in ACCOUNTS}
# Additive AI-only fictional identity; never renumber or repoint seeded accounts.
AI_DEMO_ACCOUNT = dict(demo_account_id='talent-ai-001', role='talent', candidate_id=900001)
BY_ID[AI_DEMO_ACCOUNT['demo_account_id']] = AI_DEMO_ACCOUNT
router = APIRouter(prefix='/api/demo')


def account_record(connection, account):
    if account['role'] == 'organizer':
        return {**account, 'display_name': 'Espoo Organizer Admin', 'available': True}
    talent = account['role'] == 'talent'
    table, field, name = ('candidates', 'candidate_id', 'full_name') if talent else ('companies', 'company_id', 'name')
    row = connection.execute(f'SELECT {name} FROM {table} WHERE id=?', (account[field],)).fetchone()
    return {**account, 'display_name': row[name] if row else account['demo_account_id'],
            'available': row is not None,
            **({'error': f"Required demo profile {field}={account[field]} is missing. Ask the demo operator."} if row is None else {})}


@router.get('/accounts')
def list_accounts():
    with connect() as connection:
        accounts = list(ACCOUNTS)
        if connection.execute('SELECT 1 FROM candidates WHERE id=?', (AI_DEMO_ACCOUNT['candidate_id'],)).fetchone():
            accounts.append(AI_DEMO_ACCOUNT)
        return {'accounts': [account_record(connection, account) for account in accounts],
                'candidate_count': connection.execute('SELECT count(*) FROM candidates').fetchone()[0],
                'company_count': connection.execute('SELECT count(*) FROM companies').fetchone()[0]}


def request_account(request: Request):
    values = request.headers.getlist('x-recruitifi-demo-account')
    if not values:
        return None  # Existing shared API/operator workflows remain available. This is NOT authentication.
    if len(values) != 1 or values[0] not in BY_ID:
        raise HTTPException(400, 'Unknown or ambiguous demo account. Log out and select an account again.')
    account = BY_ID[values[0]]
    with connect() as connection:
        if not account_record(connection, account)['available']:
            raise HTTPException(409, 'The selected demo profile is missing. Ask the demo operator; no fallback identity was selected.')
    return account


def require_owner(account, role, identity):
    field = 'candidate_id' if role == 'talent' else 'company_id'
    if account is not None and (account['role'] != role or account.get(field) != int(identity)):
        raise HTTPException(403, 'This operation belongs to a different demo account. Log out to switch accounts.')


async def guard_demo_identity(request: Request):
    """Reject accidental cross-account requests BEFORE endpoints process writes/uploads.

    The caller supplies a public account ID. Omitting/changing it bypasses demo
    separation; the existing shared-password middleware is the only access gate.
    """
    if not request.url.path.startswith('/api/') or request.url.path == '/api/demo/accounts' or request.method == 'OPTIONS':
        return
    account = request_account(request)
    if account is None:
        return
    path = request.url.path
    candidate = re.fullmatch(r'/api/candidates/(\d+)/(profile|skills|links|documents(?:/\d+)?|materials/\d+)', path)
    company = re.fullmatch(r'/api/companies/(\d+)/(role|matches/.+/accept)', path)
    notification = re.fullmatch(r'/api/notifications/(talent|employer)/(\d+)(?:/\d+/read)?', path)
    undo = re.fullmatch(r'/api/swipes/(talent|employer)/(\d+)/(\d+)', path)
    if candidate:
        require_owner(account, 'talent', candidate[1])
    elif company and request.method != 'GET':
        require_owner(account, 'employer', company[1])
    elif notification:
        require_owner(account, notification[1], notification[2])
    elif undo:
        require_owner(account, undo[1], undo[2] if undo[1] == 'talent' else undo[3])
    elif path == '/api/swipes' and request.method == 'PUT':
        try:
            vote = SwipeDecision.model_validate(await request.json())
        except ValueError:
            return  # Existing endpoint validation reports malformed decisions.
        require_owner(account, vote.actor, vote.candidate_id if vote.actor == 'talent' else vote.company_id)
