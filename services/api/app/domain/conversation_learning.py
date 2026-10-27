from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.jobs import JobResponse
from app.auth.dependencies import get_owned
from app.connectors.chatgpt_share import parse_pasted, parse_share_html
from app.core.errors import Problem
from app.domain.conversation_types import (
    Candidate,
    CandidateDecision,
    CandidateResponse,
    ConversationDocument,
    ConversationResponse,
    ImportConversationRequest,
    RelatedKnowledge,
)
from app.domain.knowledge_policy import lock_knowledge
from app.domain.planner import group_stages
from app.domain.planning_types import ConversationTaskRef, PlanDocument, PlanTask
from app.domain.plans import append_revision, revision_document
from app.domain.tutor import check_key, fingerprint
from app.ingestion.safe_fetch import ShareFetcher
from app.jobs.service import Handler, cancel_job, enqueue
from app.persistence.models import (
    AuditEvent,
    ConversationImport,
    Job,
    KnowledgeState,
    LearningGoal,
    LearningPlan,
)


async def create_import(
    db: AsyncSession,
    user_id: UUID,
    body: ImportConversationRequest,
    key: str,
) -> ConversationImport:
    check_key(key)
    await lock_knowledge(db, user_id)
    request_hash = fingerprint(body.model_dump(mode="json"))
    existing = await db.scalar(
        select(ConversationImport).where(
            ConversationImport.user_id == user_id,
            ConversationImport.creation_key == key,
        )
    )
    if existing:
        if existing.creation_hash != request_hash:
            raise Problem(409, "IDEMPOTENCY_CONFLICT", "此操作标识已用于不同对话材料。")
        return existing
    import_id = uuid4()
    job = await enqueue(
        db,
        user_id=user_id,
        kind="CONVERSATION_IMPORT",
        idempotency_key=fingerprint(["conversation", key]),
        payload={"import_id": str(import_id)},
        budget_units=3,
        timeout_seconds=30,
    )
    row = ConversationImport(
        id=import_id,
        user_id=user_id,
        creation_key=key,
        creation_hash=request_hash,
        source="SHARE" if body.url else "PASTED",
        source_url=body.url,
        pasted_text=body.pasted_text,
        job_id=job.id,
    )
    db.add(row)
    db.add(
        AuditEvent(
            user_id=user_id,
            operation="IMPORT_CONVERSATION",
            object_type="conversation",
            object_id=str(import_id),
            summary_code="PRIVATE_IMPORT_CONSENTED",
        )
    )
    await db.flush()
    return row


async def import_response(db: AsyncSession, row: ConversationImport) -> ConversationResponse:
    job = await get_owned(db, Job, row.user_id, row.job_id)
    candidates = (
        [Candidate.model_validate(value) for value in row.candidates]
        if job.status == "SUCCEEDED"
        else []
    )
    concept_ids = {identifier for candidate in candidates for identifier in candidate.concept_ids}
    related = (
        {
            state.concept_id: RelatedKnowledge(
                concept_id=state.concept_id,
                name=state.name,
                level=state.level,
                confidence=state.confidence,
                verified_at=state.verified_at,
                override_level=state.override_level,
            )
            for state in await db.scalars(
                select(KnowledgeState).where(
                    KnowledgeState.user_id == row.user_id,
                    KnowledgeState.concept_id.in_(concept_ids),
                )
            )
        }
        if concept_ids
        else {}
    )
    return ConversationResponse(
        id=row.id,
        source=row.source,
        url=row.source_url,
        pasted_text=row.pasted_text if job.status in {"FAILED", "CANCELLED"} else None,
        version=row.version,
        job=JobResponse.model_validate(job),
        document=ConversationDocument.model_validate(row.document)
        if row.document and job.status == "SUCCEEDED"
        else None,
        candidates=[
            CandidateResponse(
                **candidate.model_dump(),
                related=[related[item] for item in candidate.concept_ids if item in related],
            )
            for candidate in candidates
        ],
        created_at=row.created_at,
    )


async def candidate_questions(
    db: AsyncSession,
    user_id: UUID,
    document: ConversationDocument,
) -> list[Candidate]:
    states = list(
        await db.scalars(
            select(KnowledgeState)
            .where(KnowledgeState.user_id == user_id)
            .order_by(KnowledgeState.name)
            .limit(200)
        )
    )
    preferred = sorted(document.messages, key=lambda message: message.role != "USER")
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for message in preferred:
        for index, part in enumerate(message.parts):
            if part.kind != "TEXT" or not part.text.strip():
                continue
            quote = part.text.strip()[:180]
            if quote in seen:
                continue
            seen.add(quote)
            question = (
                "请用独立来源回答并检查适用条件："
                if message.role == "USER"
                else "请找独立依据核实这段材料，标出错误或不确定处："
            ) + quote
            candidates.append(
                Candidate(
                    id=uuid4(),
                    message_id=message.id,
                    part_index=index,
                    quote=quote,
                    question=question,
                    concept_ids=[
                        state.concept_id
                        for state in states
                        if state.name.casefold() in part.text.casefold()
                    ][:3],
                )
            )
            break
        if len(candidates) == 3:
            break
    if not candidates:
        message = document.messages[0]
        candidates.append(
            Candidate(
                id=uuid4(),
                message_id=message.id,
                part_index=0,
                quote=message.parts[0].text.strip()[:180],
                question="这段代码的输入、前提和预期结果是什么？请用独立来源核实，暂不运行。",
            )
        )
    return candidates


def conversation_handler(
    factory: async_sessionmaker[AsyncSession],
    fetcher: ShareFetcher | None = None,
) -> Handler:
    async def handle(job: Job) -> dict[str, object]:
        async with factory() as db:
            row = await get_owned(
                db, ConversationImport, job.user_id, UUID(str(job.payload["import_id"]))
            )
            parsed = (
                parse_share_html(await (fetcher or ShareFetcher()).fetch(row.source_url))
                if row.source_url
                else parse_pasted(row.pasted_text or "")
            )
            candidates = await candidate_questions(db, job.user_id, parsed)
            await db.refresh(row, with_for_update=True)
            current = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
            if current is None or current.status != "RUNNING" or current.lease_id != job.lease_id:
                return {}
            row.document = parsed.model_dump(mode="json")
            row.candidates = [candidate.model_dump(mode="json") for candidate in candidates]
            row.version += 1
            await db.commit()
            return {"import_id": str(row.id), "messages": len(parsed.messages)}

    return handle


async def decide_candidate(
    db: AsyncSession,
    user_id: UUID,
    import_id: UUID,
    candidate_id: UUID,
    body: CandidateDecision,
) -> ConversationImport:
    await lock_knowledge(db, user_id)
    row = await get_owned(db, ConversationImport, user_id, import_id)
    await db.refresh(row, with_for_update=True)
    job = await get_owned(db, Job, user_id, row.job_id)
    if job.status != "SUCCEEDED":
        raise Problem(409, "IMPORT_NOT_READY", "请等待导入完成，或重试失败的导入。")
    candidates = [Candidate.model_validate(value) for value in row.candidates]
    candidate = next((item for item in candidates if item.id == candidate_id), None)
    if candidate is None:
        raise Problem(404, "NOT_FOUND", "候选问题不存在或你没有访问权限。")
    target = "ADDED" if body.action == "ADD" else "DISMISSED"
    if candidate.status == target:
        if target == "ADDED" and candidate.plan_id != body.plan_id:
            raise Problem(409, "CANDIDATE_DECIDED", "此问题已加入其他计划。")
        if body.plan_id:
            await get_owned(db, LearningPlan, user_id, body.plan_id)
        return row
    if candidate.status != "PROPOSED":
        raise Problem(409, "CANDIDATE_DECIDED", "此问题已处理，不会静默覆盖先前选择。")
    if body.expected_version != row.version:
        raise Problem(409, "CONVERSATION_CONFLICT", "材料已有更新，请刷新再操作。")
    if body.action == "ADD":
        assert body.plan_id is not None
        plan = await get_owned(db, LearningPlan, user_id, body.plan_id)
        await db.refresh(plan, with_for_update=True)
        if plan.active_revision != body.expected_revision_no:
            raise Problem(409, "PLAN_CONFLICT", "计划已有新修订，请刷新后重试。")
        goal = await get_owned(db, LearningGoal, user_id, plan.goal_id)
        document = PlanDocument.model_validate((await revision_document(db, plan)).document)
        if len(document.tasks) >= 40 or body.estimated_minutes > min(
            goal.minutes_per_day, document.goal_snapshot.minutes_per_day
        ):
            raise Problem(409, "TASK_LIMIT", "任务数量或建议时间超过当前计划边界。")
        task = PlanTask(
            id=uuid4(),
            topic="对话问题核验",
            title=f"核实对话中的第 {candidates.index(candidate) + 1} 个候选问题（待验证）",
            instruction="打开所关联的对话问题，用独立来源检查原文主张、适用条件和反例。代码暂不运行；找不到依据时保留未知。",
            why="你已确认从对话材料加入此任务；AI 回答未经核验，完成不等于掌握。",
            kind="VERIFY",
            stage="INTEREST",
            estimated_minutes=body.estimated_minutes,
            origin="USER",
            conversation_ref=ConversationTaskRef(import_id=row.id, candidate_id=candidate.id),
        )
        document.tasks.insert(0, task)
        document.stages = group_stages(document.tasks)
        await append_revision(
            db, plan, document, "用户确认加入一条对话待验证问题；未产生掌握证据。"
        )
        candidate.plan_id, candidate.task_id = plan.id, task.id
    candidate.status = "ADDED" if body.action == "ADD" else "DISMISSED"
    row.candidates = [item.model_dump(mode="json") for item in candidates]
    row.version += 1
    db.add(
        AuditEvent(
            user_id=user_id,
            operation="CONVERSATION_CANDIDATE",
            object_type="conversation",
            object_id=str(row.id),
            summary_code=target,
        )
    )
    return row


async def delete_import(db: AsyncSession, user_id: UUID, import_id: UUID) -> None:
    row = await get_owned(db, ConversationImport, user_id, import_id)
    await db.refresh(row, with_for_update=True)
    job = await get_owned(db, Job, user_id, row.job_id)
    await db.refresh(job, with_for_update=True)
    await cancel_job(db, job)
    await db.delete(row)
    await db.flush()
    await db.delete(job)
    db.add(
        AuditEvent(
            user_id=user_id,
            operation="DELETE_CONVERSATION",
            object_type="conversation",
            object_id=str(import_id),
            summary_code="USER_CONFIRMED_DELETE",
        )
    )
