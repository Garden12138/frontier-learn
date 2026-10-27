import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned
from app.core.errors import Problem
from app.domain.knowledge_policy import lock_knowledge
from app.domain.planning_types import GoalInput, GoalResponse, GoalUpdate
from app.persistence.models import AuditEvent, LearningGoal


def goal_response(goal: LearningGoal) -> GoalResponse:
    return GoalResponse.model_validate(
        {name: getattr(goal, name) for name in GoalResponse.model_fields}
    )


async def create_goal(
    db: AsyncSession, user_id: UUID, body: GoalInput, idempotency_key: str
) -> LearningGoal:
    await lock_knowledge(db, user_id)
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", idempotency_key):
        raise Problem(400, "INVALID_IDEMPOTENCY_KEY", "请提供有效的目标创建标识。")
    digest = hashlib.sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    existing = await db.scalar(
        select(LearningGoal).where(
            LearningGoal.user_id == user_id, LearningGoal.creation_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.creation_hash != digest:
            raise Problem(409, "IDEMPOTENCY_CONFLICT", "此创建标识已用于不同的目标内容。")
        return existing
    count = await db.scalar(
        select(func.count()).select_from(LearningGoal).where(LearningGoal.user_id == user_id)
    )
    if (count or 0) >= 30:
        raise Problem(409, "GOAL_LIMIT", "最多保留 30 个目标，请先整理已有目标。")
    values = body.model_dump(mode="json")
    goal = LearningGoal(
        user_id=user_id, creation_key=idempotency_key, creation_hash=digest, **values
    )
    db.add(goal)
    await db.flush()
    db.add(
        AuditEvent(
            user_id=user_id,
            operation="GOAL_CREATED",
            object_type="goal",
            object_id=str(goal.id),
            summary_code="USER_GOAL",
        )
    )
    return goal


async def update_goal(
    db: AsyncSession, user_id: UUID, goal_id: UUID, body: GoalUpdate
) -> LearningGoal:
    await lock_knowledge(db, user_id)
    goal = await get_owned(db, LearningGoal, user_id, goal_id)
    await db.refresh(goal, with_for_update=True)
    if goal.version != body.version:
        raise Problem(409, "GOAL_CONFLICT", "目标已更新，请刷新后再保存。")
    for field, value in body.model_dump(mode="json", exclude={"version"}).items():
        setattr(goal, field, value)
    goal.version += 1
    goal.updated_at = datetime.now(UTC)
    db.add(
        AuditEvent(
            user_id=user_id,
            operation="GOAL_UPDATED",
            object_type="goal",
            object_id=str(goal.id),
            summary_code="VERSIONED_USER_CHANGE",
        )
    )
    return goal
