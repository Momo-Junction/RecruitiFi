from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, HttpUrl, StringConstraints

from .database import connect
from .demo_accounts import request_account, require_owner
from .models import PositiveId


router = APIRouter(prefix="/api/hiring-tasks")
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
    account = request_account(request)
    if account and account['role'] == 'organizer':
        return []
    clause, params = "", ()
    if account:
        field = 'candidate_id' if account['role'] == 'talent' else 'company_id'
        clause, params = f" WHERE {field} = ?", (account[field],)
    with connect() as connection:
        return [
            dict(row) for row in connection.execute("SELECT * FROM hiring_tasks" + clause + " ORDER BY id DESC", params)
        ]


@router.post("", response_model=HiringTask, status_code=201)
def assign_task(task: TaskAssignment, request: Request):
    require_owner(request_account(request), "employer", task.company_id)
    with connect() as connection:
        row = connection.execute(
            """
            INSERT INTO hiring_tasks (company_id, candidate_id, title, description)
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
    require_owner(request_account(request), "talent", candidate_id)
    with connect() as connection:
        row = connection.execute(
            """
            UPDATE hiring_tasks SET submission_url = ?
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
    require_owner(request_account(request), "employer", company_id)
    with connect() as connection:
        row = connection.execute(
            """
            UPDATE hiring_tasks SET verified = 1
            WHERE id = ? AND company_id = ? AND submission_url = ?
            RETURNING *
            """,
            (task_id, company_id, str(submission.url)),
        ).fetchone()
        if row is None:
            raise HTTPException(409, "The submission is unavailable or has changed. Refresh and review the current link.")
        return dict(row)
