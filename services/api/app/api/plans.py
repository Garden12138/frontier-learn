from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, Db, get_owned
from app.domain.planning_types import GeneratePlanRequest, PlanAction, PlanResponse
from app.domain.plans import act_on_plan, generate_plan, plan_response, revision_document
from app.persistence.models import LearningGoal, LearningPlan, LearningPlanRevision

router = APIRouter(tags=["Plans"])


class RevisionSummary(BaseModel):
    revision_no: int
    rationale: str
    created_at: datetime


@router.get("/plans", response_model=list[PlanResponse])
async def plans(user: CurrentUser, db: Db, goal_id: UUID | None = None) -> list[PlanResponse]:
    statement = select(LearningPlan).where(LearningPlan.user_id == user.id)
    if goal_id is not None:
        await get_owned(db, LearningGoal, user.id, goal_id)
        statement = statement.where(LearningPlan.goal_id == goal_id)
    rows = await db.scalars(statement.order_by(LearningPlan.created_at.desc()).limit(30))
    return [await plan_response(db, plan, await revision_document(db, plan)) for plan in rows]


@router.post("/plans:generate", response_model=PlanResponse)
async def generate(body: GeneratePlanRequest, user: CurrentUser, db: Db) -> PlanResponse:
    plan, revision = await generate_plan(db, user.id, body)
    await db.commit()
    return await plan_response(db, plan, revision)


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: UUID, user: CurrentUser, db: Db) -> PlanResponse:
    plan = await get_owned(db, LearningPlan, user.id, plan_id)
    return await plan_response(db, plan, await revision_document(db, plan))


@router.post("/plans/{plan_id}/actions", response_model=PlanResponse)
async def change(plan_id: UUID, body: PlanAction, user: CurrentUser, db: Db) -> PlanResponse:
    plan, revision = await act_on_plan(db, user.id, plan_id, body)
    await db.commit()
    return await plan_response(db, plan, revision)


@router.get("/plans/{plan_id}/revisions", response_model=list[RevisionSummary])
async def history(
    plan_id: UUID, user: CurrentUser, db: Db, offset: Annotated[int, Query(ge=0)] = 0
) -> list[RevisionSummary]:
    await get_owned(db, LearningPlan, user.id, plan_id)
    rows = await db.scalars(
        select(LearningPlanRevision)
        .where(LearningPlanRevision.user_id == user.id, LearningPlanRevision.plan_id == plan_id)
        .order_by(LearningPlanRevision.revision_no.desc())
        .offset(offset)
        .limit(50)
    )
    return [
        RevisionSummary(
            revision_no=row.revision_no, rationale=row.rationale, created_at=row.created_at
        )
        for row in rows
    ]


@router.get("/plans/{plan_id}/revisions/{revision_no}", response_model=PlanResponse)
async def revision(plan_id: UUID, revision_no: int, user: CurrentUser, db: Db) -> PlanResponse:
    plan = await get_owned(db, LearningPlan, user.id, plan_id)
    return await plan_response(db, plan, await revision_document(db, plan, revision_no))
