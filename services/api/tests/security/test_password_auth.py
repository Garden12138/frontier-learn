from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import digest_token
from app.persistence.models import AuthSession, PasswordCredential, User
from tests.conftest import TestDatabase

PASSWORD = "test-only password with enough entropy"


async def test_real_account_cookie_extension_mock_boundary_and_recovery(
    client: AsyncClient, pg: TestDatabase
) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"identity": "real-account", "password": PASSWORD, "client": "web"},
    )
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["access_token"] is None
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    recovery = session["recovery_code"]
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    mock = await client.post("/api/v1/auth/mock-login", json={"identity": "real-account"})
    assert mock.status_code == 403
    await client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:5173"})
    wrong = await client.post(
        "/api/v1/auth/login", json={"identity": "real-account", "password": "incorrect password"}
    )
    assert wrong.status_code == 401
    login = await client.post(
        "/api/v1/auth/login",
        json={"identity": "real-account", "password": PASSWORD, "client": "extension"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    new_password = "replacement password for test account"
    reset = await client.post(
        "/api/v1/auth/recover",
        json={"identity": "real-account", "password": new_password, "recovery_code": recovery},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["recovery_code"] != recovery
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    reused = await client.post(
        "/api/v1/auth/recover",
        json={"identity": "real-account", "password": new_password, "recovery_code": recovery},
    )
    assert reused.status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login", json={"identity": "real-account", "password": PASSWORD}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login", json={"identity": "real-account", "password": new_password}
        )
    ).status_code == 200
    export = await client.get("/api/v1/settings/export")
    assert (
        recovery not in export.text
        and PASSWORD not in export.text
        and "password_hash" not in export.text
    )
    async with pg.factory() as db:
        credential = await db.scalar(select(PasswordCredential))
        assert credential and credential.password_hash.startswith("scrypt$131072$8$1$")
        assert credential.recovery_digest == digest_token(reset.json()["recovery_code"])
        assert await db.scalar(select(AuthSession.id).where(AuthSession.auth_method == "PASSWORD"))


async def test_unknown_credentials_generic_error_origin_and_duplicate(client: AsyncClient) -> None:
    payload = {"identity": "unique-account", "password": PASSWORD}
    assert (
        await client.post(
            "/api/v1/auth/register", json=payload, headers={"Origin": "https://evil.invalid"}
        )
    ).status_code == 403
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 409
    unknown = await client.post(
        "/api/v1/auth/login", json={"identity": "does-not-exist", "password": PASSWORD}
    )
    wrong = await client.post(
        "/api/v1/auth/login", json={**payload, "password": "a different password"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["code"] == wrong.json()["code"] == "LOGIN_FAILED"


async def test_rate_limit_blocks_hash_work(client: AsyncClient, pg: TestDatabase) -> None:
    from sqlalchemy import update

    from app.persistence.models import AuthRateLimit

    await client.post("/api/v1/auth/login", json={"identity": "limited-user", "password": PASSWORD})
    async with pg.factory.begin() as db:
        await db.execute(update(AuthRateLimit).values(attempts=1001))
    response = await client.post(
        "/api/v1/auth/login", json={"identity": "limited-user", "password": PASSWORD}
    )
    assert response.status_code == 429 and response.json()["code"] == "AUTH_RATE_LIMIT"


async def test_mock_disabled_rejects_development_sessions_even_if_they_exist(
    client: AsyncClient, pg: TestDatabase
) -> None:
    from datetime import UTC, datetime, timedelta

    from cryptography.fernet import Fernet
    from httpx import ASGITransport
    from pydantic import SecretStr

    from app.core.config import Settings
    from app.main import create_app

    registered = await client.post(
        "/api/v1/auth/register",
        json={"identity": "production-account", "password": PASSWORD, "client": "extension"},
    )
    token = registered.json()["access_token"]
    async with pg.factory.begin() as db:
        user = await db.scalar(select(User).where(User.identity == "account:production-account"))
        assert user
        db.add(
            AuthSession(
                user_id=user.id,
                token_digest=digest_token("development-test-session"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                auth_method="DEVELOPMENT",
            )
        )
    for environment in ("development", "production"):
        config = Settings(
            allowed_origins=["https://learning.example"],
            database_url=SecretStr(pg.url),
            encryption_key=SecretStr(Fernet.generate_key().decode()),
        )
        app = create_app(Settings.model_validate({**config.model_dump(), "env": environment}))
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://learning.example"
            ) as deployment:
                assert (
                    await deployment.get(
                        "/api/v1/auth/me",
                        headers={"Authorization": "Bearer development-test-session"},
                    )
                ).status_code == 401
                assert (
                    await deployment.get(
                        "/api/v1/auth/me", headers={"Authorization": "Bearer " + token}
                    )
                ).status_code == 200


async def test_populated_rollback_cannot_expose_formal_data_through_mock(
    client: AsyncClient, pg: TestDatabase
) -> None:
    import asyncio
    import os
    import subprocess
    import sys
    from pathlib import Path

    import pytest
    from pydantic import ValidationError
    from sqlalchemy import func

    from app.api.auth import MockLoginRequest
    from app.persistence.models import LearningGoal

    registered = await client.post(
        "/api/v1/auth/register",
        json={"identity": "rollback-account", "password": PASSWORD, "client": "extension"},
    )
    token = registered.json()["access_token"]
    headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "rollback-formal-goal"}
    created = await client.post(
        "/api/v1/goals", headers=headers, json={"title": "保留独立学习记录", "minutes_per_day": 20}
    )
    assert created.status_code == 201
    root = Path(__file__).parents[2]

    def migrate(direction: str, target: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=root,
            env={**os.environ, "FRONTIER_DATABASE_URL": pg.url, "FRONTIER_ENV": "test"},
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0

    await asyncio.to_thread(migrate, "downgrade", "0008_ownership")
    async with pg.factory() as db:
        user = (
            await db.execute(
                select(User.id, User.identity).where(User.identity == "account:rollback-account")
            )
        ).one_or_none()
        assert user
        assert (
            await db.scalar(
                select(func.count())
                .select_from(LearningGoal)
                .where(LearningGoal.user_id == user.id)
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user.id)
            )
            == 0
        )
        # The old Mock endpoint cannot accept the stored namespace or match this private identity.
        assert await db.scalar(select(User.id).where(User.identity == "rollback-account")) is None
        with pytest.raises(ValidationError):
            MockLoginRequest(identity=user.identity)
    await asyncio.to_thread(migrate, "upgrade", "head")
    assert (
        await client.post("/api/v1/auth/mock-login", json={"identity": "rollback-account"})
    ).status_code == 403
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_account_recovery_cancels_unfinished_work(client: AsyncClient) -> None:
    from tests.test_citations import page

    session = (
        await client.post(
            "/api/v1/auth/register",
            json={"identity": "recover-jobs", "password": PASSWORD, "client": "extension"},
        )
    ).json()
    headers = {
        "Authorization": "Bearer " + session["access_token"],
        "Idempotency-Key": "recover-pending-guide",
    }
    created = await client.post(
        "/api/v1/pages:analyze", headers=headers, json={"page": page(), "consent": True}
    )
    assert created.status_code == 200
    job_id = created.json()["turns"][0]["job"]["id"]
    recovered = await client.post(
        "/api/v1/auth/recover",
        json={
            "identity": "recover-jobs",
            "password": PASSWORD + " changed",
            "recovery_code": session["recovery_code"],
        },
    )
    assert recovered.status_code == 200
    login = (
        await client.post(
            "/api/v1/auth/login",
            json={
                "identity": "recover-jobs",
                "password": PASSWORD + " changed",
                "client": "extension",
            },
        )
    ).json()
    result = await client.get(
        f"/api/v1/jobs/{job_id}", headers={"Authorization": "Bearer " + login["access_token"]}
    )
    assert result.json()["status"] == "CANCELLED"
