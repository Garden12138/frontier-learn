"""Export only owner-scoped data; never serialize credentials or authentication digests."""

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Problem
from app.domain.knowledge_policy import lock_knowledge
from app.persistence.models import (
    Assessment,
    AuditEvent,
    ConversationImport,
    GitHubConnection,
    Job,
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeSource,
    KnowledgeState,
    LearningArtifact,
    LearningGoal,
    LearningPlan,
    LearningPlanRevision,
    LearningSession,
    LearningTask,
    ModelBudget,
    ModelCall,
    OwnedEntity,
    SourceChunk,
    SourceDocument,
    TaskCompletion,
    TutorTurn,
    User,
)

EXPORT_ENTITIES: tuple[type[OwnedEntity], ...] = (
    ModelCall,
    GitHubConnection,
    KnowledgeSource,
    SourceDocument,
    SourceChunk,
    KnowledgeEvidence,
    KnowledgeState,
    LearningGoal,
    LearningPlan,
    LearningPlanRevision,
    LearningTask,
    TaskCompletion,
    LearningSession,
    TutorTurn,
    ConversationImport,
    Assessment,
    LearningArtifact,
    Job,
    AuditEvent,
)
# Keep a deny list in addition to the exact, reviewed set of exportable entity types.
SECRET_FIELDS = {
    "encrypted_token",
    "encrypted_refresh",
    "password_hash",
    "recovery_digest",
    "encrypted_verifier",
    "browser_digest",
    "session_digest",
    "state_digest",
    "encrypted_credential",
    "encrypted_write_credential",
    "token_digest",
    "creation_hash",
    "request_hash",
    "idempotency_key",
    "lease_id",
}
MAX_EXPORT_ROWS = 20000
MAX_EXPORT_BYTES = 20_000_000


async def export_data(db: AsyncSession, user: User) -> dict[str, object]:
    # A separate read snapshot keeps cross-table references consistent during imports/deletes.
    async with AsyncSession(bind=db.bind) as snapshot:
        await snapshot.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        current = await snapshot.get(User, user.id)
        if current is None:
            raise Problem(404, "NOT_FOUND", "账号已删除。")
        return await _collect_export(snapshot, current)


async def _collect_export(db: AsyncSession, user: User) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "user": {"id": str(user.id), "identity": user.public_identity},
        "settings": {"cloud_processing_allowed": user.cloud_processing_allowed},
    }
    count = 0
    encoded_bytes = 0
    for model in EXPORT_ENTITIES:
        rows = await db.stream_scalars(
            select(model)
            .where(model.user_id == user.id)
            .order_by(model.created_at, model.id)
            .limit(MAX_EXPORT_ROWS + 1)
            .execution_options(yield_per=10)
        )
        entries: list[object] = []
        async for row in rows:
            count += 1
            entry = jsonable_encoder(
                {
                    column.name: getattr(row, column.name)
                    for column in model.__table__.columns
                    if column.name not in SECRET_FIELDS
                }
            )
            encoded_bytes += len(json.dumps(entry, ensure_ascii=False).encode())
            if count > MAX_EXPORT_ROWS or encoded_bytes > MAX_EXPORT_BYTES:
                await rows.close()
                raise Problem(413, "EXPORT_LIMIT", "导出超过 20MB 或 20000 条记录，请分批处理。")
            entries.append(entry)
        result[model.__tablename__] = entries
    concepts = await db.scalars(
        select(KnowledgeConcept).where(
            exists(
                select(KnowledgeState.id).where(
                    KnowledgeState.user_id == user.id,
                    KnowledgeState.concept_id == KnowledgeConcept.id,
                )
            )
            | exists(
                select(KnowledgeEvidence.id).where(
                    KnowledgeEvidence.user_id == user.id,
                    KnowledgeEvidence.concept_id == KnowledgeConcept.id,
                )
            )
        )
    )
    budgets = await db.scalars(select(ModelBudget).where(ModelBudget.user_id == user.id))
    result["model_budgets"] = [
        {"day": row.day.isoformat(), "calls": row.calls, "reserved_tokens": row.reserved_tokens}
        for row in budgets
    ]
    result["concepts"] = [{"id": str(row.id), "name": row.canonical_name} for row in concepts]
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_EXPORT_BYTES:
        raise Problem(413, "EXPORT_LIMIT", "单次导出超过 20MB，请联系本机管理员分批导出。")
    return result


async def delete_internal_data(db: AsyncSession, user_id: UUID) -> None:
    # Same source -> job -> knowledge order as ingestion. Cancelled leases cannot save late results.
    sources = list(
        await db.scalars(
            select(KnowledgeSource)
            .where(KnowledgeSource.user_id == user_id)
            .order_by(KnowledgeSource.id)
            .with_for_update()
        )
    )
    for source in sources:
        source.status, source.encrypted_credential = "DISCONNECTED", None
        source.encrypted_write_credential, source.write_scope = None, []
        source.version += 1
    jobs = list(
        await db.scalars(
            select(Job).where(Job.user_id == user_id).order_by(Job.id).with_for_update()
        )
    )
    for job in jobs:
        job.status, job.lease_id = "CANCELLED", None
        job.finished_at = datetime.now(UTC)
    await lock_knowledge(db, user_id)
    await db.flush()
    await db.execute(delete(User).where(User.id == user_id))
    await db.flush()
    await db.execute(
        delete(KnowledgeConcept).where(
            ~exists(
                select(KnowledgeState.id).where(KnowledgeState.concept_id == KnowledgeConcept.id)
            ),
            ~exists(
                select(KnowledgeEvidence.id).where(
                    KnowledgeEvidence.concept_id == KnowledgeConcept.id
                )
            ),
        )
    )
