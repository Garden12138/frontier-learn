from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, Db, get_owned
from app.core.errors import Problem
from app.domain.conversation_learning import (
    create_import,
    decide_candidate,
    delete_import,
    import_response,
)
from app.domain.conversation_types import (
    CandidateDecision,
    ConversationResponse,
    ConversationSummary,
    ImportConversationRequest,
)
from app.persistence.models import ConversationImport, Job

router = APIRouter(tags=["Conversations"])


@router.post("/conversations:import", response_model=ConversationResponse, status_code=202)
async def import_conversation(
    body: ImportConversationRequest,
    user: CurrentUser,
    db: Db,
    key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ConversationResponse:
    row = await create_import(db, user.id, body, key)
    await db.commit()
    return await import_response(db, row)


@router.get("/conversations", response_model=list[ConversationSummary])
async def conversations(
    user: CurrentUser, db: Db, offset: Annotated[int, Query(ge=0)] = 0
) -> list[ConversationSummary]:
    rows = await db.execute(
        select(ConversationImport, Job.status)
        .join(Job, ConversationImport.job_id == Job.id)
        .where(ConversationImport.user_id == user.id, Job.user_id == user.id)
        .order_by(ConversationImport.created_at.desc())
        .offset(offset)
        .limit(30)
    )
    return [
        ConversationSummary(
            id=row.id,
            source=row.source,
            title=str(row.document.get("title", "导入材料"))
            if row.document
            else "待解析的对话材料",
            created_at=row.created_at,
            status=status,
        )
        for row, status in rows
    ]


@router.get("/conversations/{import_id}", response_model=ConversationResponse)
async def conversation(import_id: UUID, user: CurrentUser, db: Db) -> ConversationResponse:
    return await import_response(db, await get_owned(db, ConversationImport, user.id, import_id))


@router.post(
    "/conversations/{import_id}/candidates/{candidate_id}/decision",
    response_model=ConversationResponse,
)
async def decision(
    import_id: UUID,
    candidate_id: UUID,
    body: CandidateDecision,
    user: CurrentUser,
    db: Db,
) -> ConversationResponse:
    row = await decide_candidate(db, user.id, import_id, candidate_id, body)
    await db.commit()
    return await import_response(db, row)


@router.delete("/conversations/{import_id}", status_code=204)
async def remove_conversation(
    import_id: UUID, user: CurrentUser, db: Db, confirm: bool = False
) -> None:
    if not confirm:
        raise Problem(400, "CONFIRMATION_REQUIRED", "请确认删除导入对话、候选问题及关联任务记录。")
    await delete_import(db, user.id, import_id)
    await db.commit()
