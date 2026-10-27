from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned
from app.core.errors import Problem
from app.domain.knowledge_policy import lock_knowledge
from app.domain.planner import build_plan, group_stages
from app.domain.planning_types import (
    GeneratePlanRequest,
    PlanAction,
    PlanDocument,
    PlanResponse,
    PlanTask,
    SourceReference,
)
from app.persistence.models import (
    AuditEvent,
    KnowledgeEvidence,
    LearningGoal,
    LearningPlan,
    LearningPlanRevision,
    LearningTask,
    TaskCompletion,
)


async def revision_document(
    db: AsyncSession, plan: LearningPlan, revision_no: int | None = None
) -> LearningPlanRevision:
    revision = await db.scalar(
        select(LearningPlanRevision).where(
            LearningPlanRevision.user_id == plan.user_id,
            LearningPlanRevision.plan_id == plan.id,
            LearningPlanRevision.revision_no
            == (plan.active_revision if revision_no is None else revision_no),
        )
    )
    if revision is None:
        raise Problem(404, "NOT_FOUND", "计划版本不存在或你没有访问权限。")
    return revision


async def append_revision(
    db: AsyncSession, plan: LearningPlan, document: PlanDocument, rationale: str
) -> LearningPlanRevision:
    if plan.active_revision >= 200:
        raise Problem(
            409, "PLAN_REVISION_LIMIT", "此计划已达 200 次修订上限，请保留导出后整理目标。"
        )
    try:
        checked = PlanDocument.model_validate(document.model_dump())
    except ValidationError:
        raise Problem(400, "INVALID_PLAN", "计划的任务顺序、先修关系或预算无效。") from None
    revision = LearningPlanRevision(
        user_id=plan.user_id,
        plan_id=plan.id,
        revision_no=plan.active_revision + 1,
        rationale=rationale,
        document=checked.model_dump(mode="json"),
    )
    db.add(revision)
    await db.flush()
    await db.execute(
        update(LearningTask)
        .where(LearningTask.user_id == plan.user_id, LearningTask.plan_id == plan.id)
        .values(is_current=False)
    )
    for task in document.tasks:
        values = {
            "user_id": plan.user_id,
            "plan_id": plan.id,
            "revision_id": revision.id,
            "title": task.title,
            "kind": task.kind,
            "status": task.status,
            "estimated_minutes": task.estimated_minutes,
            "is_current": True,
        }
        stored = await db.scalar(
            insert(LearningTask)
            .values(id=task.id, **values)
            .on_conflict_do_update(
                index_elements=[LearningTask.id],
                set_=values,
                where=(LearningTask.user_id == plan.user_id) & (LearningTask.plan_id == plan.id),
            )
            .returning(LearningTask.id)
        )
        if stored is None:
            raise Problem(409, "TASK_CONFLICT", "任务标识不属于当前计划。")
    plan.active_revision = revision.revision_no
    db.add(
        AuditEvent(
            user_id=plan.user_id,
            operation="PLAN_REVISED",
            object_type="plan",
            object_id=str(plan.id),
            summary_code="APPEND_ONLY_REVISION",
        )
    )
    return revision


async def generate_plan(
    db: AsyncSession, user_id: UUID, body: GeneratePlanRequest
) -> tuple[LearningPlan, LearningPlanRevision]:
    await lock_knowledge(db, user_id)
    goal = await get_owned(db, LearningGoal, user_id, body.goal_id)
    await db.refresh(goal, with_for_update=True)
    if goal.version != body.goal_version:
        raise Problem(409, "GOAL_CONFLICT", "目标已变化，请刷新后重新规划。")
    if goal.status != "ACTIVE":
        raise Problem(409, "GOAL_PAUSED", "请先恢复此目标再生成计划。")
    plan = await db.scalar(
        select(LearningPlan)
        .where(LearningPlan.user_id == user_id, LearningPlan.goal_id == goal.id)
        .with_for_update()
    )
    if (plan.active_revision if plan else 0) != body.expected_revision_no:
        raise Problem(409, "PLAN_CONFLICT", "计划已变化，请刷新当前版本后重试。")
    previous = (
        PlanDocument.model_validate((await revision_document(db, plan)).document) if plan else None
    )
    if plan is None:
        plan = LearningPlan(user_id=user_id, goal_id=goal.id)
        db.add(plan)
        await db.flush()
    document = await build_plan(db, goal, previous)
    if previous:
        document.status = previous.status
    return plan, await append_revision(
        db, plan, document, "根据当前目标、证据与最近验证结果生成规则建议。"
    )


async def act_on_plan(
    db: AsyncSession, user_id: UUID, plan_id: UUID, body: PlanAction
) -> tuple[LearningPlan, LearningPlanRevision]:
    await lock_knowledge(db, user_id)
    plan = await get_owned(db, LearningPlan, user_id, plan_id)
    await db.refresh(plan, with_for_update=True)
    goal = await get_owned(db, LearningGoal, user_id, plan.goal_id)
    if body.revision_no != plan.active_revision:
        raise Problem(409, "PLAN_CONFLICT", "计划已变化，请刷新当前版本后重试。")
    document = PlanDocument.model_validate((await revision_document(db, plan)).document)
    task = next((item for item in document.tasks if item.id == body.task_id), None)
    if body.task_id is not None and task is None:
        raise Problem(404, "NOT_FOUND", "当前版本没有这个任务。")
    if body.action in {"ACCEPT", "PAUSE", "RESUME"}:
        if task:
            if task.status == "COMPLETED":
                raise Problem(
                    409, "TASK_COMPLETED", "完成记录不能通过暂停或恢复覆盖，请查看历史版本。"
                )
            task.status = "PAUSED" if body.action == "PAUSE" else "ACCEPTED"
        else:
            document.status = "PAUSED" if body.action == "PAUSE" else "ACTIVE"
            if body.action == "ACCEPT":
                for item in document.tasks:
                    if item.status == "PROPOSED":
                        item.status = "ACCEPTED"
    elif body.action in {"SKIP", "COMPLETE"}:
        if task is None:
            raise Problem(400, "TASK_REQUIRED", "请选择需要操作的任务。")
        if task.status == "COMPLETED":
            raise Problem(409, "TASK_COMPLETED", "此任务已完成，未重复记录。")
        if body.action == "SKIP":
            task.status = "SKIPPED"
        else:
            if goal.status == "PAUSED" or document.status == "PAUSED":
                raise Problem(409, "PLAN_PAUSED", "请先恢复目标和计划。")
            task.status, task.completed_at = "COMPLETED", datetime.now(UTC)
    elif body.action == "INSERT":
        if body.interest is None:
            raise Problem(400, "INTEREST_REQUIRED", "请填写临时学习内容。")
        if len(document.tasks) >= 40:
            raise Problem(
                409, "TASK_LIMIT", "当前版本最多 40 个任务，可在完成或跳过兴趣任务后重新规划。"
            )
        if body.interest.estimated_minutes > min(
            goal.minutes_per_day, document.goal_snapshot.minutes_per_day
        ):
            raise Problem(400, "TASK_TIME_LIMIT", "请将兴趣任务拆分到当前每日可用时间以内。")
        document.tasks.insert(
            0,
            PlanTask(
                id=uuid4(),
                topic=body.interest.title,
                title=body.interest.title,
                kind="USER_INTEREST",
                stage="INTEREST",
                estimated_minutes=body.interest.estimated_minutes,
                material_url=body.interest.material_url,
                origin="USER",
                instruction="围绕你选择的材料写下一个问题、一条有出处的结论与未解疑问。",
                why="用户主动插入；材料与结论未独立核实，完成不等于掌握。",
            ),
        )
    elif body.action == "REORDER":
        ids = body.ordered_task_ids or []
        if len(ids) != len(document.tasks) or set(ids) != {item.id for item in document.tasks}:
            raise Problem(400, "INVALID_TASK_ORDER", "重排必须恰好包含当前版本的全部任务。")
        by_id = {item.id: item for item in document.tasks}
        document.tasks = [by_id[item_id] for item_id in ids]
    elif body.action == "RESTORE":
        if body.restore_revision_no is None:
            raise Problem(400, "REVISION_REQUIRED", "请选择需要恢复的历史版本。")
        document = PlanDocument.model_validate(
            (await revision_document(db, plan, body.restore_revision_no)).document
        )
    document.stages = group_stages(document.tasks)
    revision = await append_revision(
        db, plan, document, f"用户操作：{body.action}。跳过与完成均不自动提升知识状态。"
    )
    if body.action == "COMPLETE" and task is not None:
        local_day = datetime.now(UTC).astimezone(ZoneInfo(goal.timezone)).date()
        await db.execute(
            insert(TaskCompletion)
            .values(
                user_id=user_id,
                task_id=task.id,
                plan_id=plan.id,
                local_day=local_day,
                timezone=goal.timezone,
                minutes=task.estimated_minutes,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    TaskCompletion.user_id,
                    TaskCompletion.task_id,
                    TaskCompletion.local_day,
                ]
            )
        )
    return plan, revision


async def plan_response(
    db: AsyncSession, plan: LearningPlan, revision: LearningPlanRevision
) -> PlanResponse:
    document = PlanDocument.model_validate(revision.document)
    goal = await get_owned(db, LearningGoal, plan.user_id, plan.goal_id)
    evidence_ids = {item for task in document.tasks for item in task.evidence_ids}
    evidence = (
        {
            item.id: item
            for item in await db.scalars(
                select(KnowledgeEvidence).where(
                    KnowledgeEvidence.user_id == plan.user_id,
                    KnowledgeEvidence.id.in_(evidence_ids),
                    KnowledgeEvidence.status == "ACTIVE",
                )
            )
        }
        if evidence_ids
        else {}
    )
    sources = [
        SourceReference(
            evidence_id=item_id,
            available=item_id in evidence,
            kind=evidence[item_id].kind if item_id in evidence else None,
            observed_at=evidence[item_id].observed_at if item_id in evidence else None,
            url=str(evidence[item_id].source_locator["url"])
            if item_id in evidence and isinstance(evidence[item_id].source_locator.get("url"), str)
            else None,
            label="可追溯的个人证据；不单独代表掌握"
            if item_id in evidence
            else "原证据已删除或撤回，当前不可用",
        )
        for item_id in sorted(evidence_ids)
    ]
    local_day = datetime.now(UTC).astimezone(ZoneInfo(goal.timezone)).date()
    used = (
        await db.scalar(
            select(func.coalesce(func.sum(TaskCompletion.minutes), 0)).where(
                TaskCompletion.user_id == plan.user_id,
                TaskCompletion.plan_id == plan.id,
                TaskCompletion.local_day == local_day,
            )
        )
        or 0
    )
    remaining = max(0, goal.minutes_per_day - used)
    today: list[UUID] = []
    permitted = {task.id for task in document.tasks if task.status in {"COMPLETED", "SKIPPED"}}
    budget = remaining
    if document.status != "PAUSED" and goal.status == "ACTIVE":
        for task in document.tasks:
            if (
                task.status in {"PROPOSED", "ACCEPTED"}
                and set(task.prerequisite_ids).issubset(permitted)
                and task.estimated_minutes <= budget
            ):
                today.append(task.id)
                permitted.add(task.id)
                budget -= task.estimated_minutes
    return PlanResponse(
        **document.model_dump(),
        id=plan.id,
        revision_no=revision.revision_no,
        rationale=revision.rationale,
        created_at=revision.created_at,
        goal_changed=goal.version != document.goal_snapshot.version,
        today_task_ids=today,
        today_completed_minutes=used,
        today_remaining_minutes=remaining,
        sources=sources,
    )
