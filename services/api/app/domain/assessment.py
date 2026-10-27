from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned
from app.core.errors import Problem
from app.domain.assessment_types import AssessmentAnswer, AssessmentFeedback, AssessmentQuestion
from app.domain.knowledge_policy import lock_knowledge
from app.domain.replanning import replan_after_evidence
from app.domain.tutoring_types import PageSnapshot
from app.ingestion.evidence import canonical_concept
from app.persistence.models import (
    Assessment,
    AuditEvent,
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeState,
    LearningGoal,
    LearningSession,
    TutorTurn,
)


async def create_assessment(db: AsyncSession, user_id: UUID, session_id: UUID) -> Assessment:
    session = await get_owned(db, LearningSession, user_id, session_id)
    await db.refresh(session, with_for_update=True)
    existing = await db.scalar(
        select(Assessment).where(Assessment.user_id == user_id, Assessment.session_id == session_id)
    )
    if existing:
        return existing
    turn = await db.scalar(
        select(TutorTurn)
        .where(
            TutorTurn.session_id == session_id,
            TutorTurn.user_id == user_id,
            TutorTurn.guide.is_not(None),
        )
        .limit(1)
    )
    if turn is None:
        raise Problem(409, "GUIDE_REQUIRED", "请先完成一轮导学再开始短测。")
    page = PageSnapshot.model_validate(session.page)
    block = next((b for b in page.blocks if b.text.strip()), page.blocks[0])
    excerpt = block.text.strip()[:600]
    goal = await db.get(LearningGoal, session.goal_id) if session.goal_id else None
    topic = goal.priorities[0] if goal and goal.priorities else goal.title if goal else page.title
    question = AssessmentQuestion(
        prompt="对照下方原文，哪一项只陈述材料明确支持的内容？",
        excerpt=excerpt,
        block_id=block.id,
        options={
            "A": "这段材料足以证明我已能在所有新场景中熟练应用。",
            "B": "这段材料直接提供了下方摘录；其外推范围仍需另外验证。",
            "C": "只要阅读并收藏这段材料，就不再需要验证理解。",
        },
        rubric=["区分原文摘录与额外推断。", "阅读或答对本题不能证明概念迁移、实践或熟练度。"],
    )
    row = Assessment(
        user_id=user_id,
        session_id=session_id,
        concept_name=topic[:160],
        question=question.model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    return row


async def answer_assessment(db: AsyncSession, row: Assessment, body: AssessmentAnswer) -> None:
    await db.refresh(row, with_for_update=True)
    if row.answer == body.choice and row.feedback is not None:
        return
    if row.version != body.version or row.answer is not None:
        raise Problem(409, "ASSESSMENT_CONFLICT", "作答已保存，请复查结果或从新会话开始。")
    correct = body.choice == "B"
    feedback = AssessmentFeedback(
        answered_at=datetime.now(UTC),
        result="SUPPORTED" if correct else "NEEDS_REVIEW",
        basis="B 只承认摘录存在，并保留外推限制；A、C 把阅读过度推断为掌握。",
        uncertainty="本题仅检查来源与推断的边界，证据强度低；尚未验证该主题的概念解释或应用能力。",
    )
    row.answer, row.feedback, row.version = (
        body.choice,
        feedback.model_dump(mode="json"),
        row.version + 1,
    )


async def confirm_assessment(db: AsyncSession, row: Assessment, version: int) -> None:
    # Use the same lock order as plan generation and source synchronization.
    await lock_knowledge(db, row.user_id)
    await db.refresh(row, with_for_update=True)
    if row.confirmed_at:
        return
    if row.version != version or row.feedback is None:
        raise Problem(409, "ASSESSMENT_CONFLICT", "请先作答并复查当前评价，再确认加入证据。")
    session = await get_owned(db, LearningSession, row.user_id, row.session_id)
    canonical = canonical_concept(row.concept_name)
    await db.execute(
        insert(KnowledgeConcept)
        .values(canonical_name=canonical)
        .on_conflict_do_nothing(index_elements=[KnowledgeConcept.canonical_name])
    )
    concept = await db.scalar(
        select(KnowledgeConcept).where(KnowledgeConcept.canonical_name == canonical)
    )
    assert concept is not None
    await db.execute(
        insert(KnowledgeState)
        .values(user_id=row.user_id, concept_id=concept.id, name=row.concept_name)
        .on_conflict_do_nothing(index_elements=[KnowledgeState.user_id, KnowledgeState.concept_id])
    )
    feedback = AssessmentFeedback.model_validate(row.feedback)
    evidence = KnowledgeEvidence(
        user_id=row.user_id,
        concept_id=concept.id,
        assessment_id=row.id,
        kind="ASSESSED",
        method="SOURCE_COMPREHENSION",
        reliability="LOW",
        polarity="POSITIVE" if feedback.result == "SUPPORTED" else "NEGATIVE",
        source_locator={
            "session_id": str(row.session_id),
            "assessment_id": str(row.id),
            "block_id": row.question["block_id"],
            "scope": "SOURCE_COMPREHENSION",
        },
        excerpt=f"来源边界短测：{feedback.result}。{feedback.uncertainty}",
    )
    db.add(evidence)
    await db.flush()
    row.evidence_id, row.confirmed_at, row.version = evidence.id, datetime.now(UTC), row.version + 1
    row.plan_revision = await replan_after_evidence(
        db,
        row.user_id,
        session.goal_id,
        f"已确认短测 {row.id}（{feedback.result}，低强度来源边界证据），"
        "下一轮先检查解释或复查；未据此判定掌握。",
    )
    db.add(
        AuditEvent(
            user_id=row.user_id,
            operation="ASSESSMENT_CONFIRMED",
            object_type="assessment",
            object_id=str(row.id),
            summary_code="LIMITED_SOURCE_EVIDENCE",
        )
    )
