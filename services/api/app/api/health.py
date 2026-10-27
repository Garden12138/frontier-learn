import asyncio
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["Health"])


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["frontier-learn"] = "frontier-learn"
    version: str = "0.1.0"


class Readiness(BaseModel):
    status: Literal["ready"] = "ready"
    database: Literal["ok"] = "ok"


@router.get("/health", response_model=Health)
async def health() -> Health:
    """Liveness deliberately does not depend on the database."""
    return Health()


@router.get("/ready", response_model=Readiness, responses={503: {"description": "Not ready"}})
async def readiness(request: Request) -> Readiness | JSONResponse:
    try:
        async with asyncio.timeout(6):
            async with request.app.state.engine.connect() as connection:
                # Readiness requires a migrated schema as well as a live database.
                await connection.execute(text("SELECT version_num FROM alembic_version"))
    except (SQLAlchemyError, OSError, TimeoutError):
        return JSONResponse(
            status_code=503,
            content={
                "code": "DATABASE_UNAVAILABLE",
                "message": "数据库尚未就绪，请检查连接和迁移。",
                "request_id": request.state.request_id,
            },
        )
    return Readiness()
