"""Bounded tutoring. Source text is data and never grants tools or write authority."""

import hashlib
import json
import re
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.budget import reserve
from app.ai.provider import LLMProvider, ModelContext, check_model_access
from app.api.jobs import JobResponse
from app.auth.dependencies import get_owned
from app.core.config import Settings
from app.core.errors import Problem
from app.domain.tutoring_types import (
    AnalyzePageRequest,
    AskRequest,
    Citation,
    Guide,
    Mode,
    PageSnapshot,
    Selection,
    SessionResponse,
    SessionSummary,
    TurnResponse,
)
from app.jobs.service import Handler, enqueue
from app.persistence.models import (
    AuditEvent,
    Job,
    KnowledgeEvidence,
    KnowledgeState,
    LearningGoal,
    LearningPlan,
    LearningSession,
    LearningTask,
    ModelCall,
    TutorTurn,
    User,
)


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def check_key(key: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
        raise Problem(400, "INVALID_IDEMPOTENCY_KEY", "请提供 8–128 位操作标识。")


def summary(session: LearningSession) -> SessionSummary:
    page = PageSnapshot.model_validate(session.page)
    return SessionSummary(
        id=session.id,
        title=page.title,
        url=page.url,
        scope=page.scope,
        version=session.version,
        goal_id=session.goal_id,
        task_id=session.task_id,
        created_at=session.created_at,
    )


async def session_response(db: AsyncSession, session: LearningSession) -> SessionResponse:
    rows = await db.execute(
        select(TutorTurn, Job)
        .join(Job, TutorTurn.job_id == Job.id)
        .where(
            TutorTurn.session_id == session.id,
            TutorTurn.user_id == session.user_id,
            Job.user_id == session.user_id,
        )
        .order_by(TutorTurn.turn_no)
        .limit(20)
    )
    return SessionResponse(
        **summary(session).model_dump(),
        page=PageSnapshot.model_validate(session.page),
        turns=[
            TurnResponse(
                id=turn.id,
                question=turn.question,
                mode=turn.mode,
                job=JobResponse.model_validate(job),
                guide=Guide.model_validate(turn.guide)
                if job.status == "SUCCEEDED" and turn.guide
                else None,
                created_at=turn.created_at,
            )
            for turn, job in rows
        ],
    )


async def add_turn(
    db: AsyncSession,
    session: LearningSession,
    key: str,
    request_hash: str,
    question: str,
    mode: Mode,
    selection: Selection | None,
    cloud_processing_allowed: bool = False,
) -> None:
    turn_id = uuid4()
    job = await enqueue(
        db,
        user_id=session.user_id,
        kind="TUTOR_GUIDE",
        idempotency_key=fingerprint([str(session.id), key]),
        payload={"turn_id": str(turn_id)},
        budget_units=3,
        timeout_seconds=30,
    )
    db.add(
        TutorTurn(
            id=turn_id,
            user_id=session.user_id,
            session_id=session.id,
            job_id=job.id,
            request_key=key,
            request_hash=request_hash,
            turn_no=session.version,
            question=question,
            mode=mode,
            cloud_processing_allowed=cloud_processing_allowed,
            selection=selection.model_dump(mode="json") if selection else None,
        )
    )
    db.add(
        AuditEvent(
            user_id=session.user_id,
            operation="TUTOR_REQUEST",
            object_type="session",
            object_id=str(session.id),
            summary_code="USER_REQUESTED_BOUNDED_GUIDE",
        )
    )
    await db.flush()


async def analyze(
    db: AsyncSession,
    user_id: UUID,
    body: AnalyzePageRequest,
    key: str,
) -> LearningSession:
    check_key(key)
    canonical = body.model_dump(mode="json")
    if not body.cloud_processing_allowed:
        canonical.pop("cloud_processing_allowed")
    request_hash = fingerprint(canonical)
    # Verify references even when resubmitting: client-supplied IDs never confer access.
    if body.goal_id:
        await get_owned(db, LearningGoal, user_id, body.goal_id)
    if body.task_id:
        task = await get_owned(db, LearningTask, user_id, body.task_id)
        plan = await get_owned(db, LearningPlan, user_id, task.plan_id)
        if plan.goal_id != body.goal_id or not task.is_current:
            raise Problem(409, "TASK_CONFLICT", "学习任务与当前目标或计划不一致。")
    session_id = uuid4()
    inserted = await db.scalar(
        insert(LearningSession)
        .values(
            id=session_id,
            user_id=user_id,
            creation_key=key,
            creation_hash=request_hash,
            page=body.page.model_dump(mode="json"),
            content_hash=fingerprint(body.page.model_dump()),
            goal_id=body.goal_id,
            task_id=body.task_id,
            version=1,
        )
        .on_conflict_do_nothing(
            index_elements=[LearningSession.user_id, LearningSession.creation_key]
        )
        .returning(LearningSession.id)
    )
    session = await db.scalar(
        select(LearningSession).where(
            LearningSession.user_id == user_id,
            LearningSession.creation_key == key,
        )
    )
    assert session is not None
    if session.creation_hash != request_hash:
        raise Problem(409, "IDEMPOTENCY_CONFLICT", "此操作标识已用于不同材料。")
    if inserted:
        await add_turn(
            db,
            session,
            key,
            request_hash,
            "请为当前材料安排阅读入口。",
            body.mode,
            body.page.selection,
            body.cloud_processing_allowed,
        )
    return session


async def ask(
    db: AsyncSession,
    user_id: UUID,
    session_id: UUID,
    body: AskRequest,
    key: str,
) -> LearningSession:
    check_key(key)
    session = await get_owned(db, LearningSession, user_id, session_id)
    await db.refresh(session, with_for_update=True)
    canonical = body.model_dump(mode="json")
    if not body.cloud_processing_allowed:
        canonical.pop("cloud_processing_allowed")
    request_hash = fingerprint(canonical)
    existing = await db.scalar(
        select(TutorTurn).where(
            TutorTurn.user_id == user_id,
            TutorTurn.session_id == session_id,
            TutorTurn.request_key == key,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise Problem(409, "IDEMPOTENCY_CONFLICT", "此操作标识已用于不同问题。")
        return session
    if session.version != body.expected_version:
        raise Problem(409, "SESSION_CONFLICT", "会话已更新，请刷新后继续。")
    if session.version >= 20:
        raise Problem(409, "SESSION_LIMIT", "本次会话已达 20 轮上限，请分段开启新会话。")
    page = PageSnapshot.model_validate(session.page)
    if body.selection and not any(
        b.id == body.selection.block_id and body.selection.quote in b.text for b in page.blocks
    ):
        raise Problem(400, "INVALID_SELECTION", "选区与当前会话材料不匹配。")
    pending = await db.scalar(
        select(Job.id)
        .join(TutorTurn, TutorTurn.job_id == Job.id)
        .where(
            TutorTurn.session_id == session_id,
            TutorTurn.user_id == user_id,
            Job.status.in_(["PENDING", "RUNNING"]),
        )
    )
    if pending:
        raise Problem(409, "GUIDE_IN_PROGRESS", "请等待当前导学，或先取消。")
    previous_selection = await db.scalar(
        select(TutorTurn.selection)
        .where(TutorTurn.session_id == session_id, TutorTurn.user_id == user_id)
        .order_by(TutorTurn.turn_no.desc())
        .limit(1)
    )
    selection = body.selection or (
        Selection.model_validate(previous_selection) if previous_selection else page.selection
    )
    session.version += 1
    await add_turn(
        db,
        session,
        key,
        request_hash,
        body.question,
        body.mode,
        selection,
        body.cloud_processing_allowed,
    )
    return session


def validate_citations(guide: Guide, page: PageSnapshot) -> Guide:
    blocks = {block.id: block for block in page.blocks}
    for citation in guide.citations:
        block = blocks.get(citation.block_id)
        matches = block is not None and citation.quote in block.text
        citation.status = (
            "SNAPSHOT_MATCH" if matches and page.provider != "MANUAL" else "UNVERIFIED"
        )
        # Never accept a model-supplied selector, even when the quoted text matches.
        citation.selector = (
            block.selector if block and matches and page.provider != "MANUAL" else ""
        )
    return guide


async def minimal_context(
    db: AsyncSession,
    session: LearningSession,
    turn: TutorTurn,
    page: PageSnapshot,
) -> ModelContext:
    goal = (
        await db.scalar(
            select(LearningGoal).where(
                LearningGoal.id == session.goal_id,
                LearningGoal.user_id == session.user_id,
            )
        )
        if session.goal_id
        else None
    )
    selection = Selection.model_validate(turn.selection) if turn.selection else None
    block = next(
        (b for b in page.blocks if selection and b.id == selection.block_id), page.blocks[0]
    )
    # Retain only one previous question, never a browser history or full conversation dump.
    previous = await db.scalar(
        select(TutorTurn.question)
        .where(
            TutorTurn.session_id == session.id,
            TutorTurn.user_id == session.user_id,
            TutorTurn.id != turn.id,
            TutorTurn.turn_no < turn.turn_no,
        )
        .order_by(TutorTurn.turn_no.desc())
        .limit(1)
    )
    task = (
        await db.scalar(
            select(LearningTask).where(
                LearningTask.id == session.task_id,
                LearningTask.user_id == session.user_id,
            )
        )
        if session.task_id
        else None
    )
    text = json.dumps(
        {
            "question": turn.question,
            "previous_question": (previous or "")[:300],
            "selected_task": task.title[:500] if task else "",
            "mode": turn.mode,
            "block_id": block.id,
            "source_excerpt": selection.quote if selection else block.text[:1800],
        },
        ensure_ascii=False,
    )[:4000]
    states = list(
        await db.scalars(
            select(KnowledgeState)
            .where(
                KnowledgeState.user_id == session.user_id,
            )
            .order_by(KnowledgeState.name)
            .limit(200)
        )
    )
    relevant = [
        s
        for s in states
        if s.name.casefold() in f"{page.title} {block.text} {goal.title if goal else ''}".casefold()
    ][:3]
    snippets: list[str] = []
    for state in relevant:
        evidence = await db.scalar(
            select(KnowledgeEvidence)
            .where(
                KnowledgeEvidence.user_id == session.user_id,
                KnowledgeEvidence.concept_id == state.concept_id,
                KnowledgeEvidence.status == "ACTIVE",
            )
            .order_by(KnowledgeEvidence.observed_at.desc())
            .limit(1)
        )
        if evidence:
            snippets.append(
                f"{state.name}: {state.level}; {evidence.reliability}; "
                f"{evidence.method}; {evidence.observed_at.isoformat()}; "
                f"{evidence.excerpt[:600]}"
            )
    preferences = await db.get(User, session.user_id)
    return ModelContext(
        user_goal=goal.title if goal else "",
        evidence_snippets=snippets,
        untrusted_text=text,
        cloud_processing_allowed=bool(
            preferences and preferences.cloud_processing_allowed and turn.cloud_processing_allowed
        ),
    )


def local_guide(page: PageSnapshot, turn: TutorTurn, context: ModelContext) -> Guide:
    selection = Selection.model_validate(turn.selection) if turn.selection else None
    block = next(
        (b for b in page.blocks if selection and b.id == selection.block_id), page.blocks[0]
    )
    first = {
        "INTUITIVE": "先用自己的话改写选定片段，给出一个生活中的例子，并标记不确定处。",
        "DEEP": "列出选定片段的前提、论证步骤与结论；缺少论证时标记待核实。",
        "PRACTICE": (
            "从选定片段提取输入、条件、预期结果和限制，写一个可检查的小实验计划；不自动运行代码。"
        ),
    }[turn.mode]
    target = f"围绕目标「{context.user_goal}」" if context.user_goal else "围绕你提出的问题"
    return Guide(
        label="LOCAL_RULES",
        summary=f"规则式导读：{target}，从「{block.heading}」的一段原文开始。"
        "这是阅读方法建议，尚未生成事实解释，也不证明已理解。",
        points=[
            "先区分原文主张、支持材料和自己的推测。",
            "当前仅有摘要，正文、图表与实验细节仍未知。"
            if page.scope == "ABSTRACT"
            else "当前仅分析提供的文本；附件、权重和图表没有核验。",
        ],
        prerequisites=[
            "先圈出不理解的术语；技术先修尚未独立确认。",
            "已有相关学习证据仍需结合验证判断。"
            if context.evidence_snippets
            else "没有找到可靠的相关知识证据，可先保留未知。",
        ],
        steps=[
            first,
            "针对本轮问题，找出一条原文依据及一个反例；找不到就保留问题。",
            "写下自己的解释与尚待验证的问题，再决定是否进一步学习。",
        ],
        citations=[
            Citation(block_id=block.id, quote=selection.quote if selection else block.text[:300])
        ],
    )


def tutor_handler(
    factory: async_sessionmaker[AsyncSession],
    provider: LLMProvider | None = None,
    *,
    settings: Settings | None = None,
    fallback_without_consent: bool = False,
) -> Handler:
    async def handle(job: Job) -> dict[str, object]:
        async with factory() as db:
            turn = await get_owned(db, TutorTurn, job.user_id, UUID(str(job.payload["turn_id"])))
            session = await get_owned(db, LearningSession, job.user_id, turn.session_id)
            page = PageSnapshot.model_validate(session.page)
            context = await minimal_context(db, session, turn, page)
            active_provider = provider
            budget_reason: str | None = None
            if (
                provider
                and provider.is_cloud
                and not context.cloud_processing_allowed
                and fallback_without_consent
            ):
                active_provider = None
            if active_provider:
                check_model_access(active_provider, context)
            reservation: ModelCall | None = None
            if active_provider and active_provider.name == "openai_responses":
                assert settings is not None
                try:
                    reservation = await reserve(
                        factory, settings, job, context, Guide.model_json_schema()
                    )
                except Problem as exc:
                    if exc.code != "MODEL_DAILY_BUDGET":
                        raise
                    active_provider, budget_reason = None, "MODEL_DAILY_BUDGET"
            if active_provider:
                check_model_access(active_provider, context)
                generated = await active_provider.generate_structured(
                    "tutor_guide",
                    context,
                    Guide,
                    max_output_units=4096,
                )
                if (
                    generated.output_units > 4096
                    or generated.input_units > 7500
                    or len(generated.output.model_dump_json()) > 4096
                ):
                    raise Problem(503, "MODEL_BUDGET", "模型响应超过本轮预算。")
                guide = generated.output
                guide.label = "MODEL_EXPLANATION"
            else:
                guide = local_guide(page, turn, context)
            if budget_reason:
                guide.summary = "今日云模型预算已用尽，改用本地阅读方法。" + guide.summary
            guide = validate_citations(guide, page)
            if reservation is not None and active_provider:
                call = await db.get(ModelCall, reservation.id)
                if call:
                    call.input_tokens, call.output_tokens = (
                        generated.input_tokens,
                        generated.output_tokens,
                    )
            # Cancellation and lease revocation win before any late answer is persisted.
            current = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
            if current is None or current.status != "RUNNING" or current.lease_id != job.lease_id:
                return {}
            turn.guide = guide.model_dump(mode="json")
            await db.commit()
            return {"session_id": str(session.id), "turn_id": str(turn.id)}

    return handle
