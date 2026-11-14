"""Persistent asymmetric demo notifications derived solely from active swipes."""
from typing import Literal

from fastapi import APIRouter, HTTPException

from .database import connect
from .models import PositiveId

Recipient = Literal['talent', 'employer']
router = APIRouter(prefix='/api/notifications')


def reconcile_pair(connection, candidate_id, company_id):
    likes = {row['actor'] for row in connection.execute(
        "SELECT actor FROM swipe_decisions WHERE candidate_id=? AND company_id=? AND decision='like'",
        (candidate_id, company_id),
    )}
    mutual = likes == {'talent', 'employer'}
    desired = {('talent', 'match'), ('employer', 'match')} if mutual else (
        {('talent', 'interest')} if 'employer' in likes else set()
    )
    # Retain history, but never expose withdrawn or superseded messages as active.
    for recipient, kind in [('talent', 'interest'), ('talent', 'match'), ('employer', 'match')]:
        params = (candidate_id, company_id, recipient, kind)
        if (recipient, kind) in desired:
            connection.execute(
                """INSERT INTO notifications(candidate_id, company_id, recipient, kind)
                   VALUES (?, ?, ?, ?) ON CONFLICT(candidate_id, company_id, recipient, kind)
                   DO UPDATE SET active=1, read_at=NULL,
                     created_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                   WHERE notifications.active=0""", params,
            )
        else:
            connection.execute(
                'UPDATE notifications SET active=0 WHERE candidate_id=? AND company_id=? AND recipient=? AND kind=?', params,
            )
    return mutual


def initialize_notifications(connection):
    # Repeatable backfill for pre-feature likes; active/read rows remain unchanged.
    pairs = connection.execute('SELECT DISTINCT candidate_id, company_id FROM swipe_decisions').fetchall()
    for row in pairs:
        reconcile_pair(connection, row['candidate_id'], row['company_id'])


def identity_column(recipient):
    return 'candidate_id' if recipient == 'talent' else 'company_id'


def check_identity(connection, recipient, identity_id):
    table = 'candidates' if recipient == 'talent' else 'companies'
    if not connection.execute(f'SELECT 1 FROM {table} WHERE id=?', (identity_id,)).fetchone():
        raise HTTPException(404, 'Demo identity not found.')


def inbox(connection, recipient, identity_id):
    rows = connection.execute(
        f"""SELECT n.*, c.name AS company_name, t.anonymous_code AS candidate_code
            FROM notifications n JOIN companies c ON c.id=n.company_id
            JOIN candidates t ON t.id=n.candidate_id
            WHERE n.recipient=? AND n.{identity_column(recipient)}=? AND n.active=1
            ORDER BY n.created_at DESC, n.id DESC""", (recipient, identity_id),
    ).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        other = item['company_name'] if recipient == 'talent' else item['candidate_code']
        item['message'] = (f"It's a Match! You and {other} liked each other."
                           if item['kind'] == 'match' else f"{other} is interested in you!")
        entries.append(item)
    return {'entries': entries, 'unread_count': sum(item['read_at'] is None for item in entries)}


@router.get('/{recipient}/{identity_id}')
def get_notifications(recipient: Recipient, identity_id: PositiveId):
    with connect() as connection:
        check_identity(connection, recipient, identity_id)
        return inbox(connection, recipient, identity_id)


@router.put('/{recipient}/{identity_id}/{notification_id}/read')
def read_notification(recipient: Recipient, identity_id: PositiveId, notification_id: PositiveId):
    with connect() as connection:
        check_identity(connection, recipient, identity_id)
        result = connection.execute(
            f"""UPDATE notifications SET read_at=COALESCE(read_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                WHERE id=? AND recipient=? AND {identity_column(recipient)}=? AND active=1""",
            (notification_id, recipient, identity_id),
        )
        if result.rowcount != 1:
            raise HTTPException(404, 'Active notification not found.')
        return inbox(connection, recipient, identity_id)
