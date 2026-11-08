import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned
from app.core.errors import Problem
from app.domain.assessment_types import (
    AssessmentAnswer,
    AssessmentCreate,
    AssessmentFeedback,
    AssessmentQuestion,
)
from app.domain.concept_assessment import enqueue_question
from app.domain.knowledge_policy import lock_knowledge
from app.domain.replanning import replan_after_evidence
from app.domain.tutoring_types import PageSnapshot
from app.ingestion.evidence import canonical_concept
from app.persistence.models import (
    Assessment,
    AuditEvent,
    Job,
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeState,
    LearningGoal,
    LearningSession,
    TutorTurn,
    User,
)


async def create_assessment(
    db: AsyncSession,
    user_id: UUID,
    session_id: UUID,
    body: AssessmentCreate | None = None,
    *,
    cloud_available: bool = False,
) -> Assessment:
    body = body or AssessmentCreate(session_id=session_id)
    session = await get_owned(db, LearningSession, user_id, session_id)
    await db.refresh(session, with_for_update=True)
    existing = await db.scalar(
        select(Assessment).where(Assessment.user_id == user_id, Assessment.session_id == session_id)
    )
    if existing:
        if existing.question.get("scope", "SOURCE_COMPREHENSION") != body.kind:
            raise Problem(
                409, "ASSESSMENT_EXISTS", "本会话已有其他类型短测；请保留原题，在新会话选择概念题。"
            )
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
    goal = await db.get(LearningGoal, session.goal_id) if session.goal_id else None
    topic = goal.priorities[0] if goal and goal.priorities else goal.title if goal else page.title
    selected = body.selection
    reason = "明确指定章节" if body.block_id else "首个非空块（未找到选区或目标匹配，请复查范围）"
    block_id = body.block_id
    if selected and block_id and selected.block_id != block_id:
        raise Problem(422, "QUESTION_SOURCE_INVALID", "选区与指定章节不一致。")
    if not selected and not block_id:
        selected = page.selection
        reason = "会话选区" if selected else reason
        if not selected:
            latest = await db.scalar(
                select(TutorTurn)
                .where(
                    TutorTurn.user_id == user_id,
                    TutorTurn.session_id == session_id,
                    TutorTurn.guide.is_not(None),
                    TutorTurn.selection.is_not(None),
                )
                .order_by(TutorTurn.turn_no.desc())
                .limit(1)
            )
            if latest and latest.selection:
                from app.domain.tutoring_types import Selection

                selected = Selection.model_validate(latest.selection)
                reason = "最近成功导学选区"
    if selected:
        block_id = selected.block_id
        if body.selection:
            reason = "本次选区"
    block = next((b for b in page.blocks if b.id == block_id), None)
    if block_id and (not block or (selected and selected.quote not in block.text)):
        raise Problem(422, "QUESTION_SOURCE_INVALID", "拟题范围不属于当前材料快照。")
    if block is None:
        terms = [
            t.casefold() for t in re.findall(r"[A-Za-z][A-Za-z-]{2,}|[\u4e00-\u9fff]{2,}", topic)
        ]
        scored = [
            (sum(t in (b.heading + " " + b.text).casefold() for t in terms), b) for b in page.blocks
        ]
        score, block = max(scored, key=lambda pair: pair[0])
        if score:
            reason = "学习目标关键词匹配（规则候选，请复查）"
    if body.block_id or selected:
        # A chapter-specific check must not create evidence for an unrelated first goal priority.
        choices = goal.priorities if goal and goal.priorities else []
        matching = [
            choice
            for choice in choices
            if choice.casefold() in (block.heading + " " + block.text).casefold()
        ]
        topic = matching[0] if matching else block.heading or page.title
    source_excerpt = selected.quote if selected else block.text[:1800]
    excerpt = source_excerpt[:600]
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
    if body.kind == "CONCEPT_CHECK":
        user = await db.get(User, user_id)
        if not body.cloud_processing_allowed or not user or not user.cloud_processing_allowed:
            raise Problem(403, "MODEL_CONSENT_REQUIRED", "概念拟题需要本次与全局模型处理授权。")
        if not cloud_available:
            raise Problem(503, "MODEL_UNAVAILABLE", "概念拟题模型未配置；可以选择来源边界题。")
        question = AssessmentQuestion(
            prompt="正在生成原文支持的概念题…",
            excerpt=source_excerpt[:600],
            block_id=block.id,
            options={},
            rubric=[],
            scope="CONCEPT_CHECK",
            source_excerpt=source_excerpt,
            source_reason=reason,
        )
    row = Assessment(
        id=uuid4(),
        user_id=user_id,
        session_id=session_id,
        concept_name=topic[:160],
        question=question.model_dump(mode="json"),
        cloud_processing_allowed=body.kind == "CONCEPT_CHECK" and body.cloud_processing_allowed,
    )
    db.add(row)
    await db.flush()
    if body.kind == "CONCEPT_CHECK":
        await enqueue_question(db, row)
    return row


async def answer_assessment(db: AsyncSession, row: Assessment, body: AssessmentAnswer) -> None:
    await db.refresh(row, with_for_update=True)
    if row.answer == body.choice and row.feedback is not None:
        return
    if row.version != body.version or row.answer is not None:
        raise Problem(409, "ASSESSMENT_CONFLICT", "作答已保存，请复查结果或从新会话开始。")
    concept = row.question.get("scope") == "CONCEPT_CHECK"
    if concept:
        job = (
            await get_owned(db, Job, row.user_id, row.question_job_id)
            if row.question_job_id
            else None
        )
        if not row.grading or not job or job.status != "SUCCEEDED":
            raise Problem(409, "QUESTION_NOT_READY", "题目尚未完成，请检查任务状态。")
    correct = body.choice == (row.grading["correct_choice"] if concept and row.grading else "B")
    feedback = AssessmentFeedback(
        answered_at=datetime.now(UTC),
        result="SUPPORTED" if correct else "NEEDS_REVIEW",
        basis=str(row.grading["basis"])
        if concept and row.grading
        else "B 只承认摘录存在，并保留外推限制；A、C 把阅读过度推断为掌握。",
        uncertainty="模型拟题和答案依据尚未独立核验；单题结果仅为低强度概念检查，不能证明主题掌握或应用能力。"
        if concept
        else "本题仅检查来源与推断的边界，证据强度低；尚未验证该主题的概念解释或应用能力。",
        method="MODEL_QUESTION_KEY" if concept else "LOCAL_RULES",
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
    concept_check = row.question.get("scope") == "CONCEPT_CHECK"
    method = "MODEL_CONCEPT_CHECK" if concept_check else "SOURCE_COMPREHENSION"
    label = "概念选择题" if concept_check else "来源边界短测"
    evidence = KnowledgeEvidence(
        user_id=row.user_id,
        concept_id=concept.id,
        assessment_id=row.id,
        kind="ASSESSED",
        method=method,
        reliability="LOW",
        polarity="POSITIVE" if feedback.result == "SUPPORTED" else "NEGATIVE",
        source_locator={
            "session_id": str(row.session_id),
            "assessment_id": str(row.id),
            "block_id": row.question["block_id"],
            "scope": method,
        },
        excerpt=f"{label}：{feedback.result}。{feedback.uncertainty}",
    )
    db.add(evidence)
    await db.flush()
    row.evidence_id, row.confirmed_at, row.version = evidence.id, datetime.now(UTC), row.version + 1
    row.plan_revision = await replan_after_evidence(
        db,
        row.user_id,
        session.goal_id,
        f"已确认短测 {row.id}（{feedback.result}，低强度{label}证据），"
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
