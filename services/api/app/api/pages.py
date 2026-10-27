from typing import Annotated

from fastapi import APIRouter, Header

from app.auth.dependencies import CurrentUser, Db
from app.domain.tutor import analyze, session_response
from app.domain.tutoring_types import AnalyzePageRequest, SessionResponse

router = APIRouter(tags=["Pages"])


@router.post("/pages:analyze", response_model=SessionResponse)
async def analyze_page(
    body: AnalyzePageRequest,
    user: CurrentUser,
    db: Db,
    key: Annotated[str, Header(alias="Idempotency-Key")],
) -> SessionResponse:
    session = await analyze(db, user.id, body, key)
    await db.commit()
    return await session_response(db, session)
