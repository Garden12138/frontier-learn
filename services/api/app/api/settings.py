from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy import update as sql_update

from app.auth.dependencies import CurrentUser, Db
from app.core.errors import Problem
from app.domain.data_portability import delete_internal_data, export_data
from app.persistence.models import AuditEvent, Job, ModelBudget

router = APIRouter(prefix="/settings", tags=["Settings"])


class SettingsResponse(BaseModel):
    version: int
    cloud_processing_allowed: bool
    active_provider: Literal["LOCAL_RULES", "OPENAI_RESPONSES"] = "LOCAL_RULES"
    cloud_provider_available: bool = False
    model: str | None = None
    calls_used_today: int = 0
    calls_limit: int = 10
    tokens_reserved_today: int = 0
    tokens_limit: int = 50000
    processing_scope: str = (
        "仅选定片段最多 4000 字符及至多 3 条相关证据，每条最多 1000 字符；"
        "不发送凭据或完整私人文档。"
    )


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    cloud_processing_allowed: bool
    confirm: Literal[True]


class DeleteDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["DELETE_MY_DATA"]


async def response_for(user: CurrentUser, db: Db, request: Request) -> SettingsResponse:
    config = request.app.state.settings
    budget = await db.scalar(
        select(ModelBudget).where(
            ModelBudget.user_id == user.id, ModelBudget.day == datetime.now(UTC).date()
        )
    )
    available = config.llm_provider == "openai_responses"
    return SettingsResponse(
        version=user.settings_version,
        cloud_processing_allowed=user.cloud_processing_allowed,
        active_provider="OPENAI_RESPONSES"
        if available and user.cloud_processing_allowed
        else "LOCAL_RULES",
        cloud_provider_available=available,
        model=config.openai_model if available else None,
        calls_used_today=budget.calls if budget else 0,
        calls_limit=config.model_user_calls_per_day,
        tokens_reserved_today=budget.reserved_tokens if budget else 0,
        tokens_limit=config.model_user_tokens_per_day,
    )


@router.get("", response_model=SettingsResponse)
async def settings(user: CurrentUser, db: Db, request: Request) -> SettingsResponse:
    return await response_for(user, db, request)


@router.put("", response_model=SettingsResponse)
async def update(
    body: SettingsUpdate, user: CurrentUser, db: Db, request: Request
) -> SettingsResponse:
    if not body.cloud_processing_allowed:
        # Same job -> user order as deletion and model admission.
        list(
            await db.scalars(
                select(Job)
                .where(
                    Job.user_id == user.id,
                    Job.kind == "TUTOR_GUIDE",
                    Job.status.in_(["PENDING", "RUNNING"]),
                )
                .order_by(Job.id)
                .with_for_update()
            )
        )
    await db.refresh(user, with_for_update=True)
    if user.settings_version != body.version:
        raise Problem(409, "SETTINGS_CONFLICT", "设置已变化，请刷新后重新确认。")
    user.cloud_processing_allowed, user.settings_version = (
        body.cloud_processing_allowed,
        user.settings_version + 1,
    )
    if not body.cloud_processing_allowed:
        await db.execute(
            sql_update(Job)
            .where(
                Job.user_id == user.id,
                Job.kind == "TUTOR_GUIDE",
                Job.status.in_(["PENDING", "RUNNING"]),
            )
            .values(status="CANCELLED", lease_id=None, finished_at=datetime.now(UTC))
        )
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="MODEL_PROCESSING_CONSENT",
            object_type="user",
            object_id=str(user.id),
            summary_code="ALLOWED" if body.cloud_processing_allowed else "DENIED",
        )
    )
    await db.commit()
    return await response_for(user, db, request)


@router.get("/export")
async def export(user: CurrentUser, db: Db, response: Response) -> dict[str, object]:
    result = await export_data(db, user)
    response.headers["Content-Disposition"] = 'attachment; filename="frontier-learning-data.json"'
    return result


@router.delete("/data", status_code=204)
async def clear(body: DeleteDataRequest, user: CurrentUser, db: Db) -> Response:
    await delete_internal_data(db, user.id)
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie("frontier_session", path="/api/v1", httponly=True, samesite="strict")
    return response
