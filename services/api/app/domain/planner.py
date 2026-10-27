import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.goals import goal_response
from app.domain.planning_types import (
    PlanDocument,
    PlanStage,
    PlanTask,
    RouteTheme,
    TaskKind,
    topic_order,
)
from app.ingestion.evidence import canonical_concept
from app.persistence.models import KnowledgeConcept, KnowledgeEvidence, KnowledgeState, LearningGoal


@dataclass
class TopicFacts:
    evidence_ids: list[UUID] = field(default_factory=list)
    concept_ids: list[UUID] = field(default_factory=list)
    latest_assessment: KnowledgeEvidence | None = None


def keywords(text: str) -> set[str]:
    words = set(re.findall(r"[a-zA-Z0-9]{2,}", text.casefold()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return words


async def learner_facts(
    db: AsyncSession, user_id: UUID, topics: list[str]
) -> dict[str, TopicFacts]:
    normalized = {canonical_concept(topic) for topic in topics}
    terms = sorted(set().union(*(keywords(topic) for topic in topics)) | normalized)[:40]
    if not terms:
        return {topic: TopicFacts() for topic in topics}
    states = list(
        await db.scalars(
            select(KnowledgeState)
            .join(KnowledgeConcept, KnowledgeConcept.id == KnowledgeState.concept_id)
            .where(
                KnowledgeState.user_id == user_id,
                or_(*(KnowledgeConcept.canonical_name.ilike(f"%{term}%") for term in terms)),
            )
            .order_by(
                case((KnowledgeConcept.canonical_name.in_(normalized), 0), else_=1),
                KnowledgeState.name,
            )
            .limit(500)
        )
    )
    matched: dict[str, list[KnowledgeState]] = {}
    for topic in topics:
        topic_terms = keywords(topic)
        ranked = sorted(
            states,
            key=lambda state: (
                canonical_concept(state.name) == canonical_concept(topic),
                len(keywords(state.name) & topic_terms),
            ),
            reverse=True,
        )
        matched[topic] = [
            state
            for state in ranked
            if canonical_concept(state.name) == canonical_concept(topic)
            or keywords(state.name) & topic_terms
        ][:4]
    concept_ids = {state.concept_id for values in matched.values() for state in values}
    evidence = (
        list(
            await db.scalars(
                select(KnowledgeEvidence)
                .where(
                    KnowledgeEvidence.user_id == user_id,
                    KnowledgeEvidence.concept_id.in_(concept_ids),
                    KnowledgeEvidence.status == "ACTIVE",
                    KnowledgeEvidence.kind != "AI_CLAIM",
                )
                .order_by(KnowledgeEvidence.observed_at.desc())
                .limit(3000)
            )
        )
        if concept_ids
        else []
    )
    result: dict[str, TopicFacts] = {}
    for topic, values in matched.items():
        ids = {state.concept_id for state in values}
        items = [item for item in evidence if item.concept_id in ids]
        assessments = [
            item for item in items if item.kind == "ASSESSED" and item.assessment_id is not None
        ]
        ordered = assessments + [item for item in items if item not in assessments]
        result[topic] = TopicFacts(
            [item.id for item in ordered[:4]],
            [state.concept_id for state in values],
            assessments[0] if assessments else None,
        )
    return result


def entry_kind(facts: TopicFacts, self_report: str) -> tuple[TaskKind, str]:
    recent = facts.latest_assessment
    if recent is not None:
        if recent.polarity == "NEGATIVE":
            return "REVIEW", "最近的验证记录提示仍有缺口，建议先复查解释与反例。"
        if recent.polarity == "POSITIVE":
            if recent.method == "SOURCE_COMPREHENSION":
                return "CHECK", "上次仅确认了原文与推断的边界；下一步用自己的例子验证概念理解。"
            if recent.observed_at >= datetime.now(UTC) - timedelta(days=30):
                return "APPLY", "最近通过了有记录的理解验证，建议把解释迁移到一个新场景。"
            return "REVIEW", "已有理解验证距今超过 30 天，建议先复查是否仍能解释。"
    if facts.evidence_ids:
        return "CHECK", "已有笔记或自报线索，尚不能证明掌握；先用自己的例子确认理解。"
    if self_report != "UNKNOWN":
        return "CHECK", "依据你的自报安排理解检查；自报尚未独立验证，不直接跳过验证。"
    return "EXPLORE", "当前缺少可靠知识证据，保留未知；先明确问题和最小材料范围。"


def group_stages(tasks: list[PlanTask]) -> list[PlanStage]:
    definitions = [
        ("ORIENT", "确认起点", "规则建议：先分清已有证据与尚未确认的问题。"),
        ("READ", "对照材料", "规则建议：围绕问题查找原文，不用阅读次数判断掌握。"),
        ("VERIFY", "验证与复盘", "规则建议：通过回答和边界例子检验理解，记录未解问题。"),
        ("INTEREST", "临时兴趣", "用户主动插入的学习内容，来源与结论尚未核实。"),
    ]
    return [
        PlanStage(
            title=title,
            why=why,
            task_ids=[task.id for task in tasks if task.stage == stage],
            estimated_minutes=sum(task.estimated_minutes for task in tasks if task.stage == stage),
        )
        for stage, title, why in definitions
        if any(task.stage == stage for task in tasks)
    ]


async def build_plan(
    db: AsyncSession, goal: LearningGoal, previous: PlanDocument | None = None
) -> PlanDocument:
    snapshot = goal_response(goal)
    topics = topic_order(goal.priorities or [goal.title], snapshot.prerequisite_edges)
    facts = await learner_facts(db, goal.user_id, topics)
    old = (
        {(task.topic, task.kind): task for task in previous.tasks if task.origin == "RULE"}
        if previous
        else {}
    )
    tasks: list[PlanTask] = []
    roadmap: list[RouteTheme] = []
    topic_last: dict[str, UUID] = {}
    for topic in topics:
        fact = facts[topic]
        kind, reason = entry_kind(fact, goal.self_report)
        earlier_entry = (
            next(
                (task for task in previous.tasks if task.topic == topic and task.stage == "ORIENT"),
                None,
            )
            if previous
            else None
        )
        new_round = bool(
            fact.latest_assessment
            and earlier_entry
            and fact.latest_assessment.id not in earlier_entry.evidence_ids
        )
        required_topics = [
            edge.prerequisite for edge in snapshot.prerequisite_edges if edge.topic == topic
        ]
        workflow_dependencies = [topic_last[name] for name in required_topics]
        specifications: list[tuple[TaskKind, str, str, str, int]] = [
            (
                kind,
                "ORIENT",
                {"EXPLORE": "明确", "CHECK": "解释", "APPLY": "迁移应用", "REVIEW": "复查"}[kind]
                + f"：{topic}",
                f"围绕「{topic}」写一个具体问题和自己的解释，再举一个例子与一个限制。不了解的词明确标记未知；可以跳过并保留不确定性。",
                10,
            ),
            (
                "READ",
                "READ",
                f"对照材料：{topic}",
                f"选择与「{topic}」相关的一段原文，标出支持结论的位置，区分来源主张和自己的推测。没有已有来源时，可先选一份自己能访问的材料。",
                15,
            ),
            (
                "VERIFY",
                "VERIFY",
                f"检查理解：{topic}",
                f"合上材料，用自己的话解释「{topic}」，给出适用条件和一个反例。把仍需验证的地方记下来；任务完成不等于通过理解验证。",
                10,
            ),
            (
                "REFLECT",
                "VERIFY",
                f"复盘：{topic}",
                "写下本次学到什么、依据在哪里、还有什么不确定。后续导学中的正式验证会单独保存，不因标记完成自动提升画像。",
                5,
            ),
        ]
        topic_tasks: list[PlanTask] = []
        for task_kind, stage, title, instruction, minutes in specifications:
            old_task = None if new_round else old.get((topic, task_kind))
            task = PlanTask(
                id=old_task.id if old_task else uuid4(),
                topic=topic,
                kind=task_kind,
                title=title,
                instruction=instruction,
                stage=stage,
                why=f"规则建议：{reason}"
                if stage == "ORIENT"
                else (
                    f"规则建议：服务于目标「{goal.title}」；"
                    "先修关系仅按用户指定的方向顺序安排，未经独立验证。"
                ),
                estimated_minutes=min(minutes, goal.minutes_per_day),
                prerequisite_ids=list(workflow_dependencies),
                prerequisite_topics=required_topics,
                evidence_ids=fact.evidence_ids,
                concept_ids=fact.concept_ids,
                status=old_task.status if old_task else "PROPOSED",
                completed_at=old_task.completed_at if old_task else None,
            )
            # New evidence can turn an already completed check into a fresh application task.
            topic_tasks.append(task)
            workflow_dependencies = [task.id]
        tasks.extend(topic_tasks)
        topic_last[topic] = topic_tasks[-1].id
        roadmap.append(
            RouteTheme(
                topic=topic,
                why=f"规则建议：{reason}",
                prerequisite_topics=required_topics,
                estimated_minutes=sum(task.estimated_minutes for task in topic_tasks),
                evidence_ids=fact.evidence_ids,
            )
        )
    if previous:
        # Preserve user-inserted interests when regenerating the rule-based route.
        tasks.extend(
            task.model_copy(deep=True)
            for task in previous.tasks
            if task.origin == "USER" and task.status not in {"COMPLETED", "SKIPPED"}
        )
    document = PlanDocument(
        goal_snapshot=snapshot,
        roadmap=roadmap,
        stages=group_stages(tasks),
        tasks=tasks,
        uncertainty="规则建议；先修关系来自用户指定，未经独立核验。阅读和任务完成不代表掌握；建议投入不是实际阅读时长承诺。",
    )
    return PlanDocument.model_validate(document.model_dump())
