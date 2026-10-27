import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import KnowledgeEvidence, KnowledgeState

LEVELS = {"UNKNOWN", "EXPOSED", "UNDERSTANDING", "APPLIED", "PROFICIENT"}


async def lock_knowledge(db: AsyncSession, user_id: UUID) -> None:
    key = int.from_bytes(
        hashlib.blake2b(b"frontier:knowledge" + user_id.bytes, digest_size=8).digest(),
        "big",
        signed=True,
    )
    await db.execute(select(func.pg_advisory_xact_lock(key)))


async def refresh_states(db: AsyncSession, user_id: UUID) -> None:
    await lock_knowledge(db, user_id)
    states = await db.scalars(select(KnowledgeState).where(KnowledgeState.user_id == user_id))
    evidence = list(
        await db.scalars(
            select(KnowledgeEvidence).where(
                KnowledgeEvidence.user_id == user_id, KnowledgeEvidence.status == "ACTIVE"
            )
        )
    )
    grouped: dict[UUID, list[KnowledgeEvidence]] = {}
    for item in evidence:
        grouped.setdefault(item.concept_id, []).append(item)
    for state in states:
        items = grouped.get(state.concept_id, [])
        verified = [
            e
            for e in items
            if e.kind == "ASSESSED"
            and e.polarity == "POSITIVE"
            and e.assessment_id is not None
            and e.method != "SOURCE_COMPREHENSION"
        ]
        # Neither note text, repository code nor an AI answer demonstrates applied skill.
        level = (
            "UNDERSTANDING"
            if verified
            else "EXPOSED"
            if any(e.kind != "AI_CLAIM" for e in items)
            else "UNKNOWN"
        )
        confidence = "MEDIUM" if verified else "LOW"
        verified_at = max((e.observed_at for e in verified), default=None)
        fingerprint = hashlib.sha256(
            ",".join(sorted(str(e.id) for e in items)).encode()
        ).hexdigest()
        new_level = state.override_level or level
        if (
            state.level != new_level
            or state.verified_at != verified_at
            or state.evidence_fingerprint != fingerprint
        ):
            state.version += 1
        state.evidence_fingerprint = fingerprint
        state.level = new_level
        state.confidence = "LOW" if state.override_level else confidence
        state.verified_at = verified_at
        state.review_due = verified_at is not None and verified_at < datetime.now(UTC) - timedelta(
            days=30
        )
