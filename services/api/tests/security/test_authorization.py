from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.api.auth import LoginResponse
from app.jobs.service import enqueue
from app.persistence.models import AuthSession, Job
from tests.conftest import TestDatabase

pytestmark = pytest.mark.postgres


async def login(client: AsyncClient, identity: str) -> LoginResponse:
    response = await client.post("/api/v1/auth/mock-login", json={"identity": identity})
    assert response.status_code == 200
    return LoginResponse.model_validate(response.json())


async def test_expiry_logout_and_digest_only_storage(client: AsyncClient, pg: TestDatabase) -> None:
    session = await login(client, "alice")
    headers = {"Authorization": f"Bearer {session.access_token}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    async with pg.factory() as db:
        stored = await db.scalar(select(AuthSession))
        assert stored is not None and session.access_token not in stored.token_digest
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    other = await login(client, "alice")
    async with pg.factory.begin() as db:
        await db.execute(
            update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    expired = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {other.access_token}"}
    )
    assert expired.status_code == 401
    assert expired.json()["code"] == "SESSION_EXPIRED"


async def test_all_job_routes_enforce_owner(client: AsyncClient, pg: TestDatabase) -> None:
    alice, bob = await login(client, "alice"), await login(client, "bob")
    async with pg.factory.begin() as db:
        job = await enqueue(
            db, user_id=alice.user_id, kind="TEST", idempotency_key="owner-key", payload={}
        )
    for method, suffix in [("GET", ""), ("POST", "/cancel"), ("POST", "/retry")]:
        denied = await client.request(
            method,
            f"/api/v1/jobs/{job.id}{suffix}",
            headers={"Authorization": f"Bearer {bob.access_token}"},
        )
        assert denied.status_code == 404
    assert (await client.get(f"/api/v1/jobs/{job.id}")).status_code == 401
    visible = await client.get(
        "/api/v1/jobs", headers={"Authorization": f"Bearer {bob.access_token}"}
    )
    assert visible.json() == []
    async with pg.factory() as db:
        stored = await db.get(Job, job.id)
        assert stored is not None and stored.status == "PENDING"
