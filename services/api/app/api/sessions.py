from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import delete, or_, select

from app.auth.dependencies import CurrentUser, Db, get_owned
from app.core.errors import Problem
from app.domain.knowledge_policy import lock_knowledge, refresh_states
from app.domain.tutor import ask, session_response, summary
from app.domain.tutoring_types import AskRequest, SessionResponse, SessionSummary
from app.jobs.service import cancel_job
from app.persistence.models import (
    Assessment,
    AuditEvent,
    Job,
    KnowledgeEvidence,
    LearningArtifact,
    LearningSession,
    TutorTurn,
)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get("", response_model=list[SessionSummary])
async def sessions(
    user: CurrentUser,
    db: Db,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SessionSummary]:
    rows = await db.scalars(
        select(LearningSession)
        .where(LearningSession.user_id == user.id)
        .order_by(LearningSession.created_at.desc())
        .offset(offset)
        .limit(30)
    )
    return [summary(row) for row in rows]


@router.get("/{session_id}", response_model=SessionResponse)
async def session(session_id: UUID, user: CurrentUser, db: Db) -> SessionResponse:
    return await session_response(db, await get_owned(db, LearningSession, user.id, session_id))


@router.post("/{session_id}/questions", response_model=SessionResponse)
async def question(
    session_id: UUID,
    body: AskRequest,
    user: CurrentUser,
    db: Db,
    key: Annotated[str, Header(alias="Idempotency-Key")],
) -> SessionResponse:
    row = await ask(db, user.id, session_id, body, key)
    await db.commit()
    return await session_response(db, row)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: UUID, user: CurrentUser, db: Db, confirm: bool = False
) -> None:
    if not confirm:
        raise Problem(400, "CONFIRMATION_REQUIRED", "请确认删除会话及其材料和追问。")
    await lock_knowledge(db, user.id)
    row = await get_owned(db, LearningSession, user.id, session_id)
    await db.refresh(row, with_for_update=True)
    jobs = list(
        await db.scalars(
            select(Job)
            .where(
                Job.user_id == user.id,
                or_(
                    Job.id.in_(select(TutorTurn.job_id).where(TutorTurn.session_id == session_id)),
                    Job.id.in_(
                        select(LearningArtifact.job_id)
                        .join(Assessment, Assessment.id == LearningArtifact.assessment_id)
                        .where(Assessment.session_id == session_id)
                    ),
                ),
            )
            .order_by(Job.id)
            .with_for_update(of=Job)
        )
    )
    for job in jobs:
        await cancel_job(db, job)
    await db.execute(
        delete(KnowledgeEvidence).where(
            KnowledgeEvidence.user_id == user.id,
            KnowledgeEvidence.assessment_id.in_(
                select(Assessment.id).where(
                    Assessment.session_id == session_id, Assessment.user_id == user.id
                )
            ),
        )
    )
    await refresh_states(db, user.id)
    await db.delete(row)
    await db.flush()
    for job in jobs:
        await db.delete(job)
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="DELETE_SESSION",
            object_type="session",
            object_id=str(session_id),
            summary_code="USER_CONFIRMED_DELETE",
        )
    )
    await db.commit()
