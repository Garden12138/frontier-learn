import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.api.artifacts import router as artifacts_router
from app.api.assessments import router as assessments_router
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.github_app import router as github_app_router
from app.api.goals import router as goals_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.knowledge import router as knowledge_router
from app.api.pages import router as pages_router
from app.api.plans import router as plans_router
from app.api.sessions import router as sessions_router
from app.api.settings import router as settings_router
from app.api.sources import router as sources_router
from app.core.config import Settings, get_settings
from app.core.errors import ErrorResponse, Problem
from app.core.logging import configure_logging
from app.core.request_limits import RequestLimits
from app.persistence.database import create_database_engine, create_session_factory

logger = logging.getLogger("frontier.requests")


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.password_slots = asyncio.Semaphore(2)
        app.state.engine = create_database_engine(config)
        app.state.sessions = create_session_factory(app.state.engine)
        yield
        await app.state.engine.dispose()

    app = FastAPI(
        title="FrontierLearn Learning API",
        version="0.1.0",
        lifespan=lifespan,
        responses={
            code: {"model": ErrorResponse}
            for code in (400, 401, 403, 404, 408, 409, 413, 422, 429, 500, 502, 503)
        },
    )
    app.state.settings = config
    app.add_middleware(RequestLimits)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = str(uuid4())
        started = monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # Exception messages, query strings and bodies may contain secrets.
            response = JSONResponse(
                status_code=500,
                content={
                    "code": "INTERNAL_ERROR",
                    "message": "服务暂不可用，请稍后重试。",
                    "request_id": request.state.request_id,
                },
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((monotonic() - started) * 1000, 2),
                }
            )
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "code": f"HTTP_{exc.status_code}",
                "message": "请求被拒绝或资源不存在。",
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(Problem)
    async def public_problem(request: Request, exc: Problem) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "INVALID_REQUEST",
                "message": "请求格式不符合要求。",
                "request_id": request.state.request_id,
            },
        )

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(github_app_router, prefix="/api/v1")
    app.include_router(jobs_router, prefix="/api/v1")
    app.include_router(sources_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(goals_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(pages_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(assessments_router, prefix="/api/v1")
    app.include_router(artifacts_router, prefix="/api/v1")
    app.include_router(settings_router, prefix="/api/v1")
    return app


app = create_app()
