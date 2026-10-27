from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert

from app.api.jobs import JobResponse
from app.auth.dependencies import CurrentUser, Db, get_owned
from app.connectors.github import normalize_prefixes, repository_ref
from app.core.errors import Problem
from app.core.security import TokenVault
from app.domain.knowledge_policy import lock_knowledge, refresh_states
from app.jobs.service import enqueue
from app.persistence.models import (
    AuditEvent,
    Job,
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeSource,
    KnowledgeState,
    SourceDocument,
)

router = APIRouter(prefix="/sources", tags=["Sources"])


class CreateSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["github"] = "github"
    external_ref: str = Field(min_length=3, max_length=256)
    read_only: Literal[True] = True
    consent: Literal[True]
    credential: SecretStr | None = Field(default=None, max_length=4000)
    path_prefixes: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("path_prefixes")
    @classmethod
    def valid_paths(cls, value: list[str]) -> list[str]:
        return normalize_prefixes(value)


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    provider: str
    github_connection_id: UUID | None = None
    external_ref: str
    status: Literal["CONNECTED", "PAUSED", "DISCONNECTED", "REAUTH_REQUIRED"]
    version: int
    read_scope: list[str]
    path_prefixes: list[str]
    write_scope: list[str]
    last_sync_at: datetime | None
    last_revision: str | None
    active_job_id: UUID | None


class SourceUpdate(BaseModel):
    version: int = Field(ge=1)
    status: Literal["CONNECTED", "PAUSED"]
    credential: SecretStr | None = Field(default=None, max_length=4000)
    path_prefixes: list[str] | None = Field(default=None, max_length=5)

    @field_validator("path_prefixes")
    @classmethod
    def valid_paths(cls, value: list[str] | None) -> list[str] | None:
        return normalize_prefixes(value) if value is not None else None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    path: str
    revision: str
    blob_sha: str
    size_bytes: int
    parse_status: str
    error_code: str | None
    is_current: bool
    renamed_from: str | None


@router.get("", response_model=list[SourceResponse])
async def list_sources(user: CurrentUser, db: Db) -> list[SourceResponse]:
    sources = await db.scalars(
        select(KnowledgeSource)
        .where(KnowledgeSource.user_id == user.id)
        .order_by(KnowledgeSource.created_at)
        .limit(100)
    )
    return [SourceResponse.model_validate(source) for source in sources]


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    body: CreateSourceRequest, user: CurrentUser, db: Db, request: Request
) -> SourceResponse:
    repository = repository_ref(body.external_ref.strip())
    encrypted = (
        TokenVault(request.app.state.settings.encryption_key).encrypt(body.credential)
        if body.credential
        else None
    )
    created_id = await db.scalar(
        insert(KnowledgeSource)
        .values(
            user_id=user.id,
            provider="github",
            external_ref=repository,
            read_scope=[repository],
            path_prefixes=body.path_prefixes,
            write_scope=[],
            encrypted_credential=encrypted,
        )
        .on_conflict_do_nothing(
            index_elements=[
                KnowledgeSource.user_id,
                KnowledgeSource.provider,
                KnowledgeSource.external_ref,
            ]
        )
        .returning(KnowledgeSource.id)
    )
    source = await db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.user_id == user.id,
            KnowledgeSource.provider == "github",
            KnowledgeSource.external_ref == repository,
        )
    )
    assert source is not None
    if created_id is None and (
        source.path_prefixes != body.path_prefixes
        or body.credential is not None
        or source.status == "DISCONNECTED"
    ):
        raise Problem(409, "SOURCE_EXISTS", "此仓库已有连接，请在该来源中修改范围或恢复授权。")
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="SOURCE_CONNECTED",
            object_type="source",
            object_id=str(source.id),
            summary_code="EXPLICIT_READ_CONSENT",
        )
    )
    await db.commit()
    return SourceResponse.model_validate(source)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID, body: SourceUpdate, user: CurrentUser, db: Db, request: Request
) -> SourceResponse:
    source = await get_owned(db, KnowledgeSource, user.id, source_id)
    await db.refresh(source, with_for_update=True)
    if source.version != body.version:
        raise Problem(409, "SOURCE_CONFLICT", "来源设置已变化，请刷新后重试。")
    source.status, source.version = body.status, source.version + 1
    if body.path_prefixes is not None:
        source.path_prefixes = body.path_prefixes
    if body.credential:
        source.encrypted_credential = TokenVault(request.app.state.settings.encryption_key).encrypt(
            body.credential
        )
    await db.execute(
        update(Job)
        .where(
            Job.user_id == user.id,
            Job.source_id == source.id,
            Job.status.in_(["PENDING", "RUNNING"]),
        )
        .values(status="CANCELLED", lease_id=None, finished_at=datetime.now(UTC))
    )
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="SOURCE_PERMISSION_UPDATED",
            object_type="source",
            object_id=str(source.id),
            summary_code=body.status,
        )
    )
    await db.commit()
    return SourceResponse.model_validate(source)


@router.post("/{source_id}/sync", response_model=JobResponse, status_code=202)
async def synchronize(
    source_id: UUID,
    user: CurrentUser,
    db: Db,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> JobResponse:
    source = await get_owned(db, KnowledgeSource, user.id, source_id)
    await db.refresh(source, with_for_update=True)
    if source.status != "CONNECTED":
        raise Problem(403, "SOURCE_DISCONNECTED", "请先恢复或重新授权该来源。")
    existing = await db.scalar(
        select(Job).where(
            Job.user_id == user.id,
            Job.kind == "GITHUB_SYNC",
            Job.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.source_id != source.id:
            raise Problem(409, "IDEMPOTENCY_CONFLICT", "操作标识已用于其他来源。")
        return JobResponse.model_validate(existing)
    active = await db.get(Job, source.active_job_id) if source.active_job_id else None
    if active is not None and active.user_id == user.id and active.status in {"PENDING", "RUNNING"}:
        return JobResponse.model_validate(active)
    job = await enqueue(
        db,
        user_id=user.id,
        source_id=source.id,
        kind="GITHUB_SYNC",
        idempotency_key=idempotency_key,
        payload={"source_version": source.version},
        timeout_seconds=120,
        budget_units=3,
    )
    source.active_job_id = job.id
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="SOURCE_SYNC",
            object_type="source",
            object_id=str(source.id),
            summary_code="BOUNDED_READ_JOB",
        )
    )
    await db.commit()
    return JobResponse.model_validate(job)


@router.get("/{source_id}/documents", response_model=list[DocumentResponse])
async def documents(source_id: UUID, user: CurrentUser, db: Db) -> list[DocumentResponse]:
    await get_owned(db, KnowledgeSource, user.id, source_id)
    rows = await db.scalars(
        select(SourceDocument)
        .where(
            SourceDocument.user_id == user.id,
            SourceDocument.source_id == source_id,
            SourceDocument.deleted_at.is_(None),
        )
        .order_by(SourceDocument.path)
        .limit(400)
    )
    return [DocumentResponse.model_validate(row) for row in rows]


@router.delete("/{source_id}", status_code=204)
async def disconnect(
    source_id: UUID, user: CurrentUser, db: Db, delete_derived: Annotated[bool, Query()] = False
) -> Response:
    source = await get_owned(db, KnowledgeSource, user.id, source_id)
    await db.refresh(source, with_for_update=True)
    source.status, source.encrypted_credential = "DISCONNECTED", None
    source.encrypted_write_credential, source.write_scope = None, []
    source.version += 1
    await db.execute(
        update(Job)
        .where(
            Job.user_id == user.id,
            Job.source_id == source_id,
            Job.status.in_(["PENDING", "RUNNING"]),
        )
        .values(status="CANCELLED", lease_id=None, finished_at=datetime.now(UTC))
    )
    if delete_derived:
        await lock_knowledge(db, user.id)
        await db.execute(
            delete(SourceDocument).where(
                SourceDocument.user_id == user.id, SourceDocument.source_id == source_id
            )
        )
        await db.execute(
            delete(KnowledgeState).where(
                KnowledgeState.user_id == user.id,
                ~exists(
                    select(KnowledgeEvidence.id).where(
                        KnowledgeEvidence.user_id == user.id,
                        KnowledgeEvidence.concept_id == KnowledgeState.concept_id,
                    )
                ),
            )
        )
        await db.execute(
            delete(KnowledgeConcept).where(
                ~exists(
                    select(KnowledgeState.id).where(
                        KnowledgeState.concept_id == KnowledgeConcept.id
                    )
                ),
                ~exists(
                    select(KnowledgeEvidence.id).where(
                        KnowledgeEvidence.concept_id == KnowledgeConcept.id
                    )
                ),
            )
        )
        await refresh_states(db, user.id)
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="SOURCE_DISCONNECTED",
            object_type="source",
            object_id=str(source.id),
            summary_code="DERIVED_REMOVED" if delete_derived else "EVIDENCE_RETAINED",
        )
    )
    await db.commit()
    return Response(status_code=204)
