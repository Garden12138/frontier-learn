import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.auth import LoginResponse
from app.core.errors import Problem
from app.jobs.service import enqueue, run_one
from app.persistence.models import Job, User
from tests.conftest import TestDatabase

pytestmark = pytest.mark.postgres


async def test_idempotency_and_concurrent_worker_claim(pg: TestDatabase) -> None:
    async with pg.factory.begin() as db:
        user = User(identity="worker-user")
        db.add(user)
        await db.flush()
        job = await enqueue(
            db, user_id=user.id, kind="TEST", idempotency_key="repeat-key", payload={"value": 1}
        )
    async with pg.factory.begin() as db:
        repeated = await enqueue(
            db, user_id=user.id, kind="TEST", idempotency_key="repeat-key", payload={"value": 1}
        )
        assert repeated.id == job.id
    with pytest.raises(Problem, match="IDEMPOTENCY_CONFLICT"):
        async with pg.factory.begin() as db:
            await enqueue(
                db, user_id=user.id, kind="TEST", idempotency_key="repeat-key", payload={"value": 2}
            )
    calls = 0

    async def handler(job: Job) -> dict[str, object]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"result_code": "TEST_PASSED"}

    await asyncio.gather(
        run_one(pg.factory, {"TEST": handler}), run_one(pg.factory, {"TEST": handler})
    )
    assert calls == 1
    async with pg.factory() as db:
        stored = await db.get(Job, job.id)
        assert stored is not None
        assert stored.status == "SUCCEEDED"
        assert stored.attempt_count == stored.spent_units == 1
    assert not await run_one(pg.factory, {"TEST": handler})


async def test_cancel_wins_over_late_completion(client: AsyncClient, pg: TestDatabase) -> None:
    login = await client.post("/api/v1/auth/mock-login", json={"identity": "cancel-user"})
    user = LoginResponse.model_validate(login.json())
    async with pg.factory.begin() as db:
        job = await enqueue(
            db, user_id=user.user_id, kind="TEST", idempotency_key="cancel-key", payload={}
        )
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(job: Job) -> dict[str, object]:
        entered.set()
        await release.wait()
        return {}

    task = asyncio.create_task(run_one(pg.factory, {"TEST": handler}))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        response = await client.post(
            f"/api/v1/jobs/{job.id}/cancel",
            headers={"Authorization": f"Bearer {user.access_token}"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"
    finally:
        release.set()
        await task
    async with pg.factory() as db:
        stored = await db.get(Job, job.id)
        assert stored is not None and stored.status == "CANCELLED"


async def test_failure_retry_backoff_and_budget(client: AsyncClient, pg: TestDatabase) -> None:
    login = await client.post("/api/v1/auth/mock-login", json={"identity": "retry-user"})
    user = LoginResponse.model_validate(login.json())
    headers = {"Authorization": f"Bearer {user.access_token}"}
    async with pg.factory.begin() as db:
        job = await enqueue(
            db,
            user_id=user.user_id,
            kind="TEST",
            idempotency_key="budget-key",
            payload={},
            budget_units=1,
        )

    async def failure(job: Job) -> dict[str, object]:
        raise RuntimeError("PRIVATE_TOKEN_AND_SOURCE_TEXT")

    assert await run_one(pg.factory, {"TEST": failure})
    status = await client.get(f"/api/v1/jobs/{job.id}", headers=headers)
    assert status.json()["status"] == "FAILED"
    assert status.json()["error_code"] == "JOB_FAILED"
    assert "PRIVATE_TOKEN" not in status.text
    retry = await client.post(f"/api/v1/jobs/{job.id}/retry", headers=headers)
    assert retry.status_code == 409
    assert retry.json()["code"] == "JOB_LIMIT"


async def test_retry_is_bounded_and_delayed(client: AsyncClient, pg: TestDatabase) -> None:
    login = await client.post("/api/v1/auth/mock-login", json={"identity": "backoff-user"})
    user = LoginResponse.model_validate(login.json())
    headers = {"Authorization": f"Bearer {user.access_token}"}
    async with pg.factory.begin() as db:
        job = await enqueue(
            db, user_id=user.user_id, kind="TEST", idempotency_key="backoff-key", payload={}
        )

    async def failure(job: Job) -> dict[str, object]:
        raise Problem(503, "UPSTREAM_UNAVAILABLE", "暂时不可用")

    for attempt in range(1, 4):
        assert await run_one(pg.factory, {"TEST": failure})
        response = await client.post(f"/api/v1/jobs/{job.id}/retry", headers=headers)
        if attempt == 3:
            assert response.status_code == 409
        else:
            assert response.json()["attempt_count"] == attempt
            assert datetime.fromisoformat(response.json()["next_attempt_at"]) > datetime.now(UTC)
            assert not await run_one(pg.factory, {"TEST": failure})
            async with pg.factory.begin() as db:
                stored = await db.scalar(select(Job).where(Job.id == job.id))
                assert stored is not None
                stored.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)


async def test_timeout_deadline_and_crashed_lease_are_observable(pg: TestDatabase) -> None:
    async with pg.factory.begin() as db:
        user = User(identity="timeout-user")
        db.add(user)
        await db.flush()
        job = await enqueue(
            db,
            user_id=user.id,
            kind="TEST",
            idempotency_key="timeout-key",
            payload={},
            timeout_seconds=1,
        )

    async def never_finishes(job: Job) -> dict[str, object]:
        await asyncio.Event().wait()
        return {}

    assert await run_one(pg.factory, {"TEST": never_finishes})
    async with pg.factory.begin() as db:
        stored = await db.get(Job, job.id)
        assert stored is not None and stored.error_code == "JOB_TIMEOUT"
        expired = await enqueue(
            db, user_id=user.id, kind="TEST", idempotency_key="expired-key", payload={}
        )
        expired.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        crashed = await enqueue(
            db, user_id=user.id, kind="TEST", idempotency_key="crashed-key", payload={}
        )
        crashed.status = "RUNNING"
        crashed.attempt_count = crashed.spent_units = 1
        crashed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not await run_one(pg.factory, {"TEST": never_finishes})
    async with pg.factory() as db:
        recovered = await db.get(Job, crashed.id)
        stopped = await db.get(Job, expired.id)
        assert recovered is not None and recovered.status == "FAILED"
        assert recovered.error_code == "WORKER_LEASE_EXPIRED"
        assert stopped is not None and stopped.error_code == "JOB_EXPIRED"
