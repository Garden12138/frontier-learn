import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.main import create_app


@asynccontextmanager
async def api_client(settings: Settings | None = None) -> AsyncIterator[AsyncClient]:
    app = create_app(settings or Settings(env="test"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def test_liveness_does_not_require_database() -> None:
    async with api_client() as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "frontier-learn", "version": "0.1.0"}
    assert UUID(response.headers["x-request-id"])
    assert response.headers["cache-control"] == "no-store"


async def test_readiness_failure_does_not_leak_database_credentials() -> None:
    settings = Settings(
        env="test",
        database_url=SecretStr("postgresql+asyncpg://secret:private@127.0.0.1:1/missing"),
    )
    async with api_client(settings) as client:
        response = await client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "secret" not in response.text
    assert "private" not in response.text


async def test_request_logs_have_no_query_or_untrusted_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="frontier.requests"):
        async with api_client() as client:
            response = await client.get(
                "/api/v1/health?token=PRIVATE_TOKEN", headers={"X-Request-ID": "PRIVATE_TOKEN"}
            )
    entries = [record.message for record in caplog.records if record.name == "frontier.requests"]
    assert len(entries) == 1
    assert "PRIVATE_TOKEN" not in entries[0]
    assert response.headers["x-request-id"] != "PRIVATE_TOKEN"


def test_production_rejects_mock_auth_and_missing_secrets() -> None:
    with pytest.raises(ValidationError, match="Mock identity"):
        Settings(env="production", mock_auth=True)
    with pytest.raises(ValidationError, match="encryption key"):
        Settings(env="production")


async def test_unknown_route_uses_standard_error() -> None:
    async with api_client() as client:
        response = await client.get("/unknown")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message", "request_id"}


async def test_mock_identity_is_disabled_by_default() -> None:
    async with api_client() as client:
        response = await client.post("/api/v1/auth/mock-login", json={"identity": "demo"})
    assert response.status_code == 404
    assert response.json()["code"] == "MOCK_AUTH_DISABLED"
