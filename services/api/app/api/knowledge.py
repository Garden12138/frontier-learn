from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from app.auth.dependencies import CurrentUser, Db
from app.core.errors import Problem
from app.domain.knowledge_policy import lock_knowledge, refresh_states
from app.persistence.models import AuditEvent, KnowledgeEvidence, KnowledgeState

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])
Level = Literal["UNKNOWN", "EXPOSED", "UNDERSTANDING", "APPLIED", "PROFICIENT"]


class KnowledgeResponse(BaseModel):
    concept_id: UUID
    name: str
    level: Level
    confidence: str
    evidence_count: int
    review_due: bool
    verified_at: datetime | None
    version: int
    override_reason: str | None
    override_level: Level | None


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    concept_id: UUID
    document_id: UUID | None
    kind: str
    source_locator: dict[str, object]
    excerpt: str
    observed_at: datetime
    reliability: str
    method: str
    status: str


class CorrectionRequest(BaseModel):
    level: Level | None
    reason: str = Field(min_length=3, max_length=1000)
    version: int = Field(ge=1)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("A correction requires a meaningful reason")
        return value


@router.get("", response_model=list[KnowledgeResponse])
async def profile(
    user: CurrentUser,
    db: Db,
    q: Annotated[str, Query(max_length=200)] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[KnowledgeResponse]:
    counts = (
        select(KnowledgeEvidence.concept_id, func.count().label("total"))
        .where(KnowledgeEvidence.user_id == user.id, KnowledgeEvidence.status == "ACTIVE")
        .group_by(KnowledgeEvidence.concept_id)
        .subquery()
    )
    rows = await db.execute(
        select(KnowledgeState, func.coalesce(counts.c.total, 0))
        .outerjoin(counts, counts.c.concept_id == KnowledgeState.concept_id)
        .where(KnowledgeState.user_id == user.id, KnowledgeState.name.ilike(f"%{q}%"))
        .order_by(KnowledgeState.name)
        .offset(offset)
        .limit(limit)
    )
    return [
        KnowledgeResponse(
            concept_id=s.concept_id,
            name=s.name,
            level=s.level,
            confidence=s.confidence,
            evidence_count=count,
            review_due=s.review_due,
            verified_at=s.verified_at,
            version=s.version,
            override_reason=s.override_reason,
            override_level=s.override_level,
        )
        for s, count in rows
    ]


@router.get("/{concept_id}/evidence", response_model=list[EvidenceResponse])
async def evidence(concept_id: UUID, user: CurrentUser, db: Db) -> list[EvidenceResponse]:
    state = await db.scalar(
        select(KnowledgeState).where(
            KnowledgeState.user_id == user.id, KnowledgeState.concept_id == concept_id
        )
    )
    if state is None:
        raise Problem(404, "NOT_FOUND", "知识点不存在或你没有访问权限。")
    items = await db.scalars(
        select(KnowledgeEvidence)
        .where(
            KnowledgeEvidence.user_id == user.id,
            KnowledgeEvidence.concept_id == concept_id,
            KnowledgeEvidence.status == "ACTIVE",
        )
        .order_by(KnowledgeEvidence.observed_at.desc())
        .limit(100)
    )
    return [EvidenceResponse.model_validate(item) for item in items]


@router.patch("/{concept_id}", response_model=KnowledgeResponse)
async def correct(
    concept_id: UUID, body: CorrectionRequest, user: CurrentUser, db: Db
) -> KnowledgeResponse:
    await lock_knowledge(db, user.id)
    state = await db.scalar(
        select(KnowledgeState)
        .where(KnowledgeState.user_id == user.id, KnowledgeState.concept_id == concept_id)
        .with_for_update()
    )
    if state is None:
        raise Problem(404, "NOT_FOUND", "知识点不存在或你没有访问权限。")
    if state.version != body.version:
        raise Problem(409, "KNOWLEDGE_CONFLICT", "知识状态已变化，请刷新后再修改。")
    state.override_level, state.override_reason = body.level, body.reason.strip()
    state.version += 1
    db.add(
        KnowledgeEvidence(
            user_id=user.id,
            concept_id=concept_id,
            kind="USER_CORRECTION",
            reliability="SELF_REPORT",
            method="USER_STATEMENT",
            source_locator={"provider": "user", "reason": body.reason},
            excerpt=body.reason,
        )
    )
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="KNOWLEDGE_CORRECTED",
            object_type="concept",
            object_id=str(concept_id),
            summary_code="USER_STATEMENT",
        )
    )
    await db.flush()
    await refresh_states(db, user.id)
    await db.commit()
    count = await db.scalar(
        select(func.count())
        .select_from(KnowledgeEvidence)
        .where(
            KnowledgeEvidence.user_id == user.id,
            KnowledgeEvidence.concept_id == concept_id,
            KnowledgeEvidence.status == "ACTIVE",
        )
    )
    return KnowledgeResponse(
        concept_id=state.concept_id,
        name=state.name,
        level=state.level,
        confidence=state.confidence,
        evidence_count=count or 0,
        review_due=state.review_due,
        verified_at=state.verified_at,
        version=state.version,
        override_reason=state.override_reason,
        override_level=state.override_level,
    )
