import asyncio

from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.ai.openai_provider import OpenAIProvider
from app.core.config import Settings
from app.domain.tutor import tutor_handler
from app.ingestion.http_reader import ReadResponse
from app.jobs.service import run_one
from app.persistence.models import Job, ModelBudget, ModelCall, TutorTurn
from tests.conftest import TestDatabase
from tests.planning_fixture import authenticate
from tests.test_citations import create
from tests.test_openai_provider import ResponsesFixture


async def consent(client: AsyncClient, headers: dict[str, str], allowed: bool) -> None:
    settings = (await client.get("/api/v1/settings", headers=headers)).json()
    result = await client.put(
        "/api/v1/settings",
        headers=headers,
        json={"version": settings["version"], "cloud_processing_allowed": allowed, "confirm": True},
    )
    assert result.status_code == 200


async def test_consent_and_daily_quota_fall_back_without_a_paid_request(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    fixture = ResponsesFixture()
    provider = OpenAIProvider(SecretStr("fixture-model-secret"), "configured-test-model", fixture)
    settings = Settings(model_user_calls_per_day=1, model_global_calls_per_day=2)
    handler = tutor_handler(pg.factory, provider, settings=settings, fallback_without_consent=True)
    await create(client, headers, cloud_processing_allowed=True)
    await run_one(pg.factory, {"TUTOR_GUIDE": handler})
    assert fixture.calls == []
    await consent(client, headers, True)
    await create(client, headers, cloud_processing_allowed=True)
    await run_one(pg.factory, {"TUTOR_GUIDE": handler})
    assert len(fixture.calls) == 1
    last = await create(client, headers, cloud_processing_allowed=True)
    await run_one(pg.factory, {"TUTOR_GUIDE": handler})
    reply = (await client.get(f"/api/v1/sessions/{last.id}", headers=headers)).json()
    assert reply["turns"][0]["guide"]["label"] == "LOCAL_RULES"
    assert "预算" in reply["turns"][0]["guide"]["summary"]
    assert len(fixture.calls) == 1
    async with pg.factory() as db:
        calls = list(await db.scalars(select(ModelCall)))
        assert len(calls) == 1 and calls[0].input_tokens == 200 and calls[0].output_tokens == 150
        budgets = list(await db.scalars(select(ModelBudget)))
        assert all(row.calls == 1 and row.reserved_tokens > 2048 for row in budgets)


async def test_global_budget_survives_account_deletion(
    client: AsyncClient, pg: TestDatabase
) -> None:
    fixture = ResponsesFixture()
    provider = OpenAIProvider(SecretStr("fixture-model-secret"), "configured-test-model", fixture)
    handler = tutor_handler(
        pg.factory,
        provider,
        settings=Settings(model_global_calls_per_day=1),
        fallback_without_consent=True,
    )
    first = await authenticate(client, "budget-first")
    await consent(client, first, True)
    await create(client, first, cloud_processing_allowed=True)
    await run_one(pg.factory, {"TUTOR_GUIDE": handler})
    assert (
        await client.request(
            "DELETE",
            "/api/v1/settings/data",
            headers=first,
            json={"confirmation": "DELETE_MY_DATA"},
        )
    ).status_code == 204
    second = await authenticate(client, "budget-second")
    await consent(client, second, True)
    await create(client, second, cloud_processing_allowed=True)
    await run_one(pg.factory, {"TUTOR_GUIDE": handler})
    assert len(fixture.calls) == 1
    async with pg.factory() as db:
        assert await db.scalar(select(ModelBudget.calls).where(ModelBudget.scope == "GLOBAL")) == 1
        assert await db.scalar(select(func.count()).select_from(ModelCall)) == 0


async def test_failed_network_does_not_refund_uncertain_cost(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    await consent(client, headers, True)
    fixture = ResponsesFixture()
    fixture.status = 500
    provider = OpenAIProvider(SecretStr("fixture-model-secret"), "configured-test-model", fixture)
    await create(client, headers, cloud_processing_allowed=True)
    await run_one(
        pg.factory, {"TUTOR_GUIDE": tutor_handler(pg.factory, provider, settings=Settings())}
    )
    async with pg.factory() as db:
        assert await db.scalar(select(Job.status)) == "FAILED"
        assert await db.scalar(select(ModelBudget.calls).where(ModelBudget.scope == "GLOBAL")) == 1
        call = await db.scalar(select(ModelCall))
        assert call and call.input_tokens is None


async def test_revoke_consent_during_model_call_prevents_late_answer(
    client: AsyncClient, pg: TestDatabase
) -> None:
    class BlockingFixture(ResponsesFixture):
        def __init__(self) -> None:
            super().__init__()
            self.started, self.release = asyncio.Event(), asyncio.Event()

        async def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            max_bytes: int,
            content: bytes = b"",
        ) -> ReadResponse:
            self.started.set()
            await self.release.wait()
            return await super().request(
                method, url, headers=headers, max_bytes=max_bytes, content=content
            )

    headers = await authenticate(client)
    await consent(client, headers, True)
    await create(client, headers, cloud_processing_allowed=True)
    fixture = BlockingFixture()
    task = asyncio.create_task(
        run_one(
            pg.factory,
            {
                "TUTOR_GUIDE": tutor_handler(
                    pg.factory,
                    OpenAIProvider(
                        SecretStr("fixture-model-secret"), "configured-test-model", fixture
                    ),
                    settings=Settings(),
                )
            },
        )
    )
    await asyncio.wait_for(fixture.started.wait(), timeout=10)
    await consent(client, headers, False)
    fixture.release.set()
    await task
    async with pg.factory() as db:
        assert await db.scalar(select(Job.status)) == "CANCELLED"
        turn = await db.scalar(select(TutorTurn))
        assert turn and turn.guide is None


async def test_global_consent_does_not_override_a_local_only_turn(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    await consent(client, headers, True)
    fixture = ResponsesFixture()
    session = await create(client, headers)
    await run_one(
        pg.factory,
        {
            "TUTOR_GUIDE": tutor_handler(
                pg.factory,
                OpenAIProvider(SecretStr("fixture-model-secret"), "configured-test-model", fixture),
                settings=Settings(),
                fallback_without_consent=True,
            )
        },
    )
    assert fixture.calls == []
    reply = (await client.get(f"/api/v1/sessions/{session.id}", headers=headers)).json()
    assert reply["turns"][0]["guide"]["label"] == "LOCAL_RULES"
