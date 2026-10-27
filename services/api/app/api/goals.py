from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, Db, get_owned
from app.core.errors import Problem
from app.domain.goals import create_goal, goal_response, update_goal
from app.domain.knowledge_policy import lock_knowledge
from app.domain.planning_types import GoalInput, GoalResponse, GoalUpdate
from app.persistence.models import AuditEvent, LearningGoal

router = APIRouter(prefix="/goals", tags=["Goals"])


@router.get("", response_model=list[GoalResponse])
async def goals(user: CurrentUser, db: Db) -> list[GoalResponse]:
    items = await db.scalars(
        select(LearningGoal)
        .where(LearningGoal.user_id == user.id)
        .order_by(LearningGoal.created_at.desc())
        .limit(30)
    )
    return [goal_response(item) for item in items]


@router.post("", status_code=201, response_model=GoalResponse)
async def add_goal(
    body: GoalInput,
    user: CurrentUser,
    db: Db,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> GoalResponse:
    goal = await create_goal(db, user.id, body, idempotency_key)
    await db.commit()
    return goal_response(goal)


@router.put("/{goal_id}", response_model=GoalResponse)
async def edit_goal(goal_id: UUID, body: GoalUpdate, user: CurrentUser, db: Db) -> GoalResponse:
    goal = await update_goal(db, user.id, goal_id, body)
    await db.commit()
    return goal_response(goal)


@router.delete("/{goal_id}", status_code=204)
async def remove_goal(
    goal_id: UUID, user: CurrentUser, db: Db, confirm: Annotated[bool, Query()] = False
) -> Response:
    if not confirm:
        raise Problem(400, "CONFIRMATION_REQUIRED", "删除目标及其计划历史前需要确认。")
    await lock_knowledge(db, user.id)
    goal = await get_owned(db, LearningGoal, user.id, goal_id)
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="GOAL_DELETED",
            object_type="goal",
            object_id=str(goal.id),
            summary_code="USER_CONFIRMED_INTERNAL_DELETE",
        )
    )
    await db.delete(goal)
    await db.commit()
    return Response(status_code=204)
