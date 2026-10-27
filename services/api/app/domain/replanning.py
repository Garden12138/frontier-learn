from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.knowledge_policy import refresh_states
from app.domain.planning_types import GeneratePlanRequest
from app.domain.plans import generate_plan
from app.persistence.models import LearningGoal, LearningPlan


async def replan_after_evidence(
    db: AsyncSession, user_id: UUID, goal_id: UUID | None, reason: str
) -> int | None:
    await refresh_states(db, user_id)
    if goal_id is None:
        return None
    goal = await db.get(LearningGoal, goal_id)
    plan = await db.scalar(
        select(LearningPlan).where(LearningPlan.user_id == user_id, LearningPlan.goal_id == goal_id)
    )
    if goal is None or goal.user_id != user_id or goal.status != "ACTIVE" or plan is None:
        return None
    # Keep confirmation available when a plan reaches its bounded revision limit.
    if plan.active_revision >= 200:
        return None
    _, revision = await generate_plan(
        db,
        user_id,
        GeneratePlanRequest(
            goal_id=goal_id, goal_version=goal.version, expected_revision_no=plan.active_revision
        ),
    )
    revision.rationale = reason[:1200]
    return revision.revision_no
