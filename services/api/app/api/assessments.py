from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, Db, get_owned
from app.domain.assessment import answer_assessment, confirm_assessment, create_assessment
from app.domain.assessment_types import (
    AssessmentAnswer,
    AssessmentCreate,
    AssessmentResponse,
    ConfirmEvidence,
)
from app.persistence.models import Assessment

router = APIRouter(prefix="/assessments", tags=["Assessments"])


@router.get("", response_model=list[AssessmentResponse])
async def assessments(user: CurrentUser, db: Db) -> list[AssessmentResponse]:
    rows = await db.scalars(
        select(Assessment)
        .where(Assessment.user_id == user.id)
        .order_by(Assessment.created_at.desc())
        .limit(100)
    )
    return [AssessmentResponse.model_validate(row) for row in rows]


@router.post("", response_model=AssessmentResponse, status_code=201)
async def create(body: AssessmentCreate, user: CurrentUser, db: Db) -> AssessmentResponse:
    row = await create_assessment(db, user.id, body.session_id)
    await db.commit()
    return AssessmentResponse.model_validate(row)


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get(assessment_id: UUID, user: CurrentUser, db: Db) -> AssessmentResponse:
    return AssessmentResponse.model_validate(
        await get_owned(db, Assessment, user.id, assessment_id)
    )


@router.post("/{assessment_id}/answer", response_model=AssessmentResponse)
async def answer(
    assessment_id: UUID, body: AssessmentAnswer, user: CurrentUser, db: Db
) -> AssessmentResponse:
    row = await get_owned(db, Assessment, user.id, assessment_id)
    await answer_assessment(db, row, body)
    await db.commit()
    return AssessmentResponse.model_validate(row)


@router.post("/{assessment_id}/confirm", response_model=AssessmentResponse)
async def confirm(
    assessment_id: UUID, body: ConfirmEvidence, user: CurrentUser, db: Db
) -> AssessmentResponse:
    row = await get_owned(db, Assessment, user.id, assessment_id)
    await confirm_assessment(db, row, body.version)
    await db.commit()
    return AssessmentResponse.model_validate(row)
