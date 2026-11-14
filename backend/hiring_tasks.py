from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response, Depends
from pydantic import BaseModel, HttpUrl, StringConstraints

from .database import connect
from .demo_accounts import require_owner
from .evidence.sessions import session
from .models import PositiveId


def task_account(request:Request,response:Response):
    data,account=session(request,write=request.method not in ('GET','HEAD'))
    selected=request.headers.get('x-recruitifi-demo-account')
    if selected is not None and selected!=data['account']:raise HTTPException(403,'Selected account does not match the verified session.')
    request.state.hiring_account=account
    response.headers['Cache-Control']='no-store'
    return account


router = APIRouter(prefix="/api/hiring-tasks",dependencies=[Depends(task_account)])
TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
TaskDescription = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class TaskAssignment(BaseModel):
    candidate_id: PositiveId
    company_id: PositiveId
    title: TaskTitle
    description: TaskDescription


class TaskSubmission(BaseModel):
    url: HttpUrl


class HiringTask(TaskAssignment):
    id: PositiveId
    submission_url: str | None
    verified: bool


@router.get("", response_model=list[HiringTask])
def list_tasks(request: Request):
    account = request.state.hiring_account
    if account and account['role'] == 'organizer':
        return []
    clause, params = "", ()
    if account:
        field = 'candidate_id' if account['role'] == 'talent' else 'company_id'
        clause, params = f" WHERE {field} = ?", (account[field],)
    with connect() as connection:
        return [
            dict(row) for row in connection.execute("SELECT * FROM hiring_task_assignments" + clause + " ORDER BY id DESC", params)
        ]


@router.post("", response_model=HiringTask, status_code=201)
def assign_task(task: TaskAssignment, request: Request):
    require_owner(request.state.hiring_account, "employer", task.company_id)
    with connect() as connection:
        row = connection.execute(
            """
            INSERT INTO hiring_task_assignments (company_id, candidate_id, title, description)
            SELECT company_id, candidate_id, ?, ? FROM swipe_decisions
            WHERE company_id = ? AND candidate_id = ? AND actor = 'employer' AND decision = 'like'
            RETURNING *
            """,
            (task.title, task.description, task.company_id, task.candidate_id),
        ).fetchone()
        if row is None:
            raise HTTPException(409, "Shortlist this candidate before assigning a task.")
        return dict(row)


@router.put("/{task_id}/submission/{candidate_id}", response_model=HiringTask)
def submit_task(task_id: PositiveId, candidate_id: PositiveId, submission: TaskSubmission, request: Request):
    require_owner(request.state.hiring_account, "talent", candidate_id)
    with connect() as connection:
        row = connection.execute(
            """
            UPDATE hiring_task_assignments SET submission_url = ?
            WHERE id = ? AND candidate_id = ? AND verified = 0
            RETURNING *
            """,
            (str(submission.url), task_id, candidate_id),
        ).fetchone()
        if row is None:
            raise HTTPException(409, "This task is unavailable or has already been verified.")
        return dict(row)


@router.put("/{task_id}/verification/{company_id}", response_model=HiringTask)
def verify_task(task_id: PositiveId, company_id: PositiveId, submission: TaskSubmission, request: Request):
    require_owner(request.state.hiring_account, "employer", company_id)
    with connect() as connection:
        row = connection.execute(
            """
            UPDATE hiring_task_assignments SET verified = 1
            WHERE id = ? AND company_id = ? AND submission_url = ?
            RETURNING *
            """,
            (task_id, company_id, str(submission.url)),
        ).fetchone()
        if row is None:
            raise HTTPException(409, "The submission is unavailable or has changed. Refresh and review the current link.")
        return dict(row)


def initialize_tasks(connection):
    """Copy compatible pulled task rows once, retaining every legacy table/row.

    An abandoned pipeline used the same table name with different columns.
    Never reinterpret that layout or drop it. The new namespace avoids collision.
    """
    columns={row[1] for row in connection.execute('PRAGMA table_info(hiring_tasks)')}
    required={'id','candidate_id','company_id','title','description','submission_url','verified'}
    if required<=columns:
        connection.execute("""INSERT OR IGNORE INTO hiring_task_assignments(id,candidate_id,company_id,title,description,submission_url,verified)
            SELECT id,candidate_id,company_id,title,description,submission_url,verified FROM hiring_tasks""")
