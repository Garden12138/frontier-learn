from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, Db, get_owned
from app.core.errors import Problem
from app.jobs.service import cancel_job, retry_job
from app.persistence.models import AuditEvent, Job, KnowledgeSource, LearningSession, TutorTurn

router = APIRouter(prefix="/jobs", tags=["Jobs"])


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID | None
    kind: str
    status: Literal["PENDING", "RUNNING", "PARTIAL", "SUCCEEDED", "FAILED", "CANCELLED"]
    attempt_count: int
    max_attempts: int
    budget_units: int
    spent_units: int
    progress: float
    error_code: str | None
    deadline_at: datetime
    next_attempt_at: datetime


@router.get("", response_model=list[JobResponse])
async def list_jobs(user: CurrentUser, db: Db) -> list[JobResponse]:
    jobs = await db.scalars(
        select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(100)
    )
    return [JobResponse.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def job_status(job_id: UUID, user: CurrentUser, db: Db) -> JobResponse:
    return JobResponse.model_validate(await get_owned(db, Job, user.id, job_id))


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry(job_id: UUID, user: CurrentUser, db: Db) -> JobResponse:
    job = await get_owned(db, Job, user.id, job_id)
    if job.kind == "TUTOR_GUIDE":
        turn = await db.scalar(
            select(TutorTurn).where(
                TutorTurn.user_id == user.id,
                TutorTurn.job_id == job.id,
            )
        )
        if turn is None:
            raise Problem(404, "NOT_FOUND", "导学会话已删除。")
        session = await get_owned(db, LearningSession, user.id, turn.session_id)
        await db.refresh(session, with_for_update=True)
        latest = await db.scalar(
            select(TutorTurn.id)
            .where(
                TutorTurn.session_id == session.id,
                TutorTurn.user_id == user.id,
            )
            .order_by(TutorTurn.turn_no.desc())
            .limit(1)
        )
        if latest != turn.id:
            raise Problem(409, "TURN_SUPERSEDED", "已有后续提问，请从最新一轮继续学习。")
    source = None
    if job.kind in {"GITHUB_SYNC", "GITHUB_WRITEBACK"} and job.source_id is not None:
        source = await get_owned(db, KnowledgeSource, user.id, job.source_id)
        await db.refresh(source, with_for_update=True)
        if source.status != "CONNECTED" or source.version != job.payload.get("source_version"):
            raise Problem(409, "SOURCE_CONFLICT", "来源授权已变化，请重新发起同步。")
        active = (
            await db.get(Job, source.active_job_id)
            if source.active_job_id and job.kind == "GITHUB_SYNC"
            else None
        )
        if active is not None and active.id != job.id and active.status in {"PENDING", "RUNNING"}:
            raise Problem(409, "SYNC_IN_PROGRESS", "此来源已有同步任务，请等待或取消该任务。")
    # Serialize concurrent retries/cancels with the worker claim.
    await db.refresh(job, with_for_update=True)
    await retry_job(db, job)
    if source is not None and job.kind == "GITHUB_SYNC":
        source.active_job_id = job.id
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="JOB_RETRY",
            object_type="job",
            object_id=str(job.id),
            summary_code="BOUNDED_RETRY",
        )
    )
    await db.commit()
    return JobResponse.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel(job_id: UUID, user: CurrentUser, db: Db) -> JobResponse:
    job = await get_owned(db, Job, user.id, job_id)
    await db.refresh(job, with_for_update=True)
    await cancel_job(db, job)
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="JOB_CANCEL",
            object_type="job",
            object_id=str(job.id),
            summary_code="USER_CANCELLED",
        )
    )
    await db.commit()
    return JobResponse.model_validate(job)
