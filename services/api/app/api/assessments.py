from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select, true

from app.auth.dependencies import CurrentUser, Db, get_owned
from app.domain.assessment import answer_assessment, confirm_assessment, create_assessment
from app.domain.assessment_types import (
    AssessmentAnswer,
    AssessmentCreate,
    AssessmentResponse,
    ConfirmEvidence,
)
from app.domain.concept_assessment import assessment_response
from app.persistence.models import Assessment

router = APIRouter(prefix="/assessments", tags=["Assessments"])


@router.get("", response_model=list[AssessmentResponse])
async def assessments(
    user: CurrentUser, db: Db, session_id: UUID | None = None
) -> list[AssessmentResponse]:
    if session_id:
        from app.persistence.models import LearningSession

        await get_owned(db, LearningSession, user.id, session_id)
    rows = await db.scalars(
        select(Assessment)
        .where(Assessment.user_id == user.id)
        .where(Assessment.session_id == session_id if session_id else true())
        .order_by(Assessment.created_at.desc())
        .limit(100)
    )
    return [await assessment_response(db, row) for row in rows]


@router.post("", response_model=AssessmentResponse, status_code=201)
async def create(
    body: AssessmentCreate, user: CurrentUser, db: Db, request: Request
) -> AssessmentResponse:
    row = await create_assessment(
        db,
        user.id,
        body.session_id,
        body,
        cloud_available=request.app.state.settings.llm_provider == "openai_responses",
    )
    await db.commit()
    return await assessment_response(db, row)


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get(assessment_id: UUID, user: CurrentUser, db: Db) -> AssessmentResponse:
    return await assessment_response(db, await get_owned(db, Assessment, user.id, assessment_id))


@router.post("/{assessment_id}/answer", response_model=AssessmentResponse)
async def answer(
    assessment_id: UUID, body: AssessmentAnswer, user: CurrentUser, db: Db
) -> AssessmentResponse:
    row = await get_owned(db, Assessment, user.id, assessment_id)
    await answer_assessment(db, row, body)
    await db.commit()
    return await assessment_response(db, row)


@router.post("/{assessment_id}/confirm", response_model=AssessmentResponse)
async def confirm(
    assessment_id: UUID, body: ConfirmEvidence, user: CurrentUser, db: Db
) -> AssessmentResponse:
    row = await get_owned(db, Assessment, user.id, assessment_id)
    await confirm_assessment(db, row, body.version)
    await db.commit()
    return await assessment_response(db, row)
