import asyncio
import json
from collections.abc import AsyncIterator
from typing import TypedDict, cast
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.ai.fake_provider import FakeProvider
from app.ai.provider import Generated, ModelContext, Output
from app.core.config import Settings
from app.domain.concept_assessment import concept_handler
from app.domain.planning_types import PlanDocument
from app.domain.tutor import tutor_handler
from app.jobs.service import run_one
from app.main import create_app
from app.persistence.models import (
    Assessment,
    Job,
    KnowledgeEvidence,
    KnowledgeState,
    LearningPlanRevision,
)
from tests.conftest import TestDatabase
from tests.integration.test_model_budget import consent
from tests.planning_fixture import authenticate, generate, make_goal
from tests.test_citations import create, page

SOURCE = (
    "Byte pair encoding starts with individual symbols and repeatedly merges the most frequent "
    "adjacent pair. It stops when the merge budget is exhausted."
)


def candidate() -> dict[str, object]:
    return {
        "prompt": "根据材料，BPE 的合并预算耗尽后，合并过程会如何处理？",
        "options": {
            "A": "继续执行直到只剩一个符号。",
            "B": "自动恢复预算并重新开始合并。",
            "C": "停止继续进行符号对合并。",
        },
        "correct_choice": "C",
        "rubric": ["识别材料说明的停止条件。", "区分停止条件与未经材料支持的继续或重启。"],
        "basis": "模型答案依据：预算耗尽时停止，C 符合该条件；A、B 的继续或重启未获原文支持。",
        "block_id": "b0",
        "quote": "It stops when the merge budget is exhausted.",
    }


class QuestionProvider(FakeProvider):
    def __init__(self, *, blocking: bool = False) -> None:
        super().__init__({"concept_question": candidate()})
        self.contexts: list[ModelContext] = []
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.blocking = blocking

    async def generate_structured(
        self, operation: str, context: ModelContext, schema: type[Output], *, max_output_units: int
    ) -> Generated[Output]:
        self.contexts.append(context)
        self.started.set()
        if self.blocking:
            await self.release.wait()
        return await super().generate_structured(
            operation, context, schema, max_output_units=max_output_units
        )


@pytest.fixture
async def concept_client(pg: TestDatabase) -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(
            env="test",
            database_url=SecretStr(pg.url),
            mock_auth=True,
            llm_provider="openai_responses",
            openai_api_key=SecretStr("fixture-model-secret"),
            openai_model="configured-test-model",
        )
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def prepare(
    client: AsyncClient, pg: TestDatabase, headers: dict[str, str], goal_id: UUID | None = None
) -> UUID:
    material = page()
    material["blocks"] = [{"id": "b0", "heading": "BPE", "text": SOURCE, "selector": "p"}]
    session = await create(
        client, headers, page=material, **({"goal_id": str(goal_id)} if goal_id else {})
    )
    await run_one(pg.factory, {"TUTOR_GUIDE": tutor_handler(pg.factory)})
    return session.id


class QuestionJob(TypedDict):
    id: str


class PendingQuestion(TypedDict):
    id: str
    version: int
    job: QuestionJob


async def request_question(
    client: AsyncClient, headers: dict[str, str], session_id: UUID
) -> PendingQuestion:
    response = await client.post(
        "/api/v1/assessments",
        headers=headers,
        json={
            "session_id": str(session_id),
            "kind": "CONCEPT_CHECK",
            "cloud_processing_allowed": True,
        },
    )
    assert response.status_code == 201, response.text
    assert "grading" not in response.json() and "correct_choice" not in response.text
    return cast(PendingQuestion, response.json())


async def test_two_concept_checks_grade_saved_key_and_replan_conservatively(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    goal = await make_goal(client, headers, title="BPE")
    plan = await generate(client, headers, goal)
    provider = QuestionProvider()
    for choice in ("C", "A"):
        session_id = await prepare(client, pg, headers, goal.id)
        pending = await request_question(client, headers, session_id)
        repeat = await request_question(client, headers, session_id)
        assert repeat["id"] == pending["id"]
        assert (
            await client.post(
                f"/api/v1/assessments/{pending['id']}/answer",
                headers=headers,
                json={"version": 1, "choice": choice},
            )
        ).status_code == 409
        assert await run_one(
            pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, provider, Settings())}
        )
        ready = (await client.get(f"/api/v1/assessments/{pending['id']}", headers=headers)).json()
        assert (
            ready["question"]["scope"] == "CONCEPT_CHECK" and ready["job"]["status"] == "SUCCEEDED"
        )
        assert "correct_choice" not in json.dumps(ready) and "grading" not in ready
        answered = await client.post(
            f"/api/v1/assessments/{pending['id']}/answer",
            headers=headers,
            json={"version": ready["version"], "choice": choice},
        )
        assert answered.status_code == 200, answered.text
        result = answered.json()
        assert result["feedback"]["result"] == ("SUPPORTED" if choice == "C" else "NEEDS_REVIEW")
        assert result["feedback"]["method"] == "MODEL_QUESTION_KEY"
        assert "C 符合" in result["feedback"]["basis"]
        confirmed = await client.post(
            f"/api/v1/assessments/{pending['id']}/confirm",
            headers=headers,
            json={"version": result["version"], "confirm": True},
        )
        assert confirmed.status_code == 200, confirmed.text
    assert len(provider.contexts) == 2 and all(
        context.evidence_snippets == [] for context in provider.contexts
    )
    assert len(provider.contexts[0].untrusted_text) < 2000
    async with pg.factory() as db:
        state = await db.scalar(select(KnowledgeState))
        assert state and state.level == "EXPOSED" and state.confidence == "LOW"
        evidence = list(await db.scalars(select(KnowledgeEvidence)))
        assert len(evidence) == 2 and all(
            e.method == "MODEL_CONCEPT_CHECK" and e.reliability == "LOW" for e in evidence
        )
        revisions = list(
            await db.scalars(
                select(LearningPlanRevision)
                .where(LearningPlanRevision.plan_id == plan.id)
                .order_by(LearningPlanRevision.revision_no)
            )
        )
        assert PlanDocument.model_validate(revisions[1].document).tasks[0].kind == "CHECK"
        assert PlanDocument.model_validate(revisions[2].document).tasks[0].kind == "REVIEW"
        assert "概念选择题" in revisions[2].rationale


async def test_missing_consent_forged_source_and_cross_user_are_rejected(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    session_id = await prepare(client, pg, headers)
    response = await client.post(
        "/api/v1/assessments",
        headers=headers,
        json={
            "session_id": str(session_id),
            "kind": "CONCEPT_CHECK",
            "cloud_processing_allowed": True,
        },
    )
    assert response.status_code == 403
    await consent(client, headers, True)
    other = await authenticate(client, "other-concept-user")
    assert (
        await client.get(f"/api/v1/assessments?session_id={session_id}", headers=other)
    ).status_code == 404
    pending = await request_question(client, headers, session_id)
    provider = QuestionProvider()
    provider.responses["concept_question"]["quote"] = (
        "This quote does not exist in the given source."
    )
    await run_one(
        pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, provider, Settings())}
    )
    failed = (await client.get(f"/api/v1/assessments/{pending['id']}", headers=headers)).json()
    assert (
        failed["job"]["status"] == "FAILED"
        and failed["job"]["error_code"] == "QUESTION_CITATION_INVALID"
    )
    assert failed["question"]["options"] == {}
    async with pg.factory() as db:
        row = await db.get(Assessment, UUID(str(pending["id"])))
        assert row and row.grading is None
    assert (
        await client.get(f"/api/v1/assessments/{pending['id']}", headers=other)
    ).status_code == 404


async def test_revocation_during_generation_discards_late_question_and_session_delete_cleans_job(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    session_id = await prepare(client, pg, headers)
    pending = await request_question(client, headers, session_id)
    provider = QuestionProvider(blocking=True)
    task = asyncio.create_task(
        run_one(
            pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, provider, Settings())}
        )
    )
    await asyncio.wait_for(provider.started.wait(), timeout=10)
    await consent(client, headers, False)
    provider.release.set()
    await task
    result = (await client.get(f"/api/v1/assessments/{pending['id']}", headers=headers)).json()
    assert result["job"]["status"] == "CANCELLED" and result["question"]["options"] == {}
    deleted = await client.delete(f"/api/v1/sessions/{session_id}?confirm=true", headers=headers)
    assert deleted.status_code == 204, deleted.text
    async with pg.factory() as db:
        assert await db.get(Assessment, UUID(str(pending["id"]))) is None
        assert await db.scalar(select(Job)) is None


async def test_rubric_is_hidden_on_all_preanswer_routes(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    session_id = await prepare(client, pg, headers)
    pending = await request_question(client, headers, session_id)
    provider = QuestionProvider()
    provider.responses["concept_question"]["rubric"] = ["正确答案 C，因为预算耗尽后停止合并。"]
    await run_one(
        pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, provider, Settings())}
    )
    for url in (
        f"/api/v1/assessments/{pending['id']}",
        f"/api/v1/assessments?session_id={session_id}",
        "/api/v1/settings/export",
    ):
        response = await client.get(url, headers=headers)
        assert "正确答案 C" not in response.text
        assert "correct_choice" not in response.text
    ready = (await client.get(f"/api/v1/assessments/{pending['id']}", headers=headers)).json()
    assert ready["question"]["rubric"] == []
    answered = await client.post(
        f"/api/v1/assessments/{pending['id']}/answer",
        headers=headers,
        json={"version": ready["version"], "choice": "C"},
    )
    assert answered.json()["question"]["rubric"] == ["正确答案 C，因为预算耗尽后停止合并。"]


async def test_cancelled_generation_can_recover_idempotently_without_reusing_job(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    pending = await request_question(client, headers, await prepare(client, pg, headers))
    await client.post(f"/api/v1/jobs/{pending['job']['id']}/cancel", headers=headers)
    body = {"version": pending["version"], "cloud_processing_allowed": True}
    recovered = await client.post(
        f"/api/v1/assessments/{pending['id']}/regenerate", headers=headers, json=body
    )
    assert recovered.status_code == 200, recovered.text
    current = recovered.json()
    assert current["job"]["id"] != pending["job"]["id"]
    assert current["job"]["status"] == "PENDING"
    repeated = await client.post(
        f"/api/v1/assessments/{pending['id']}/regenerate", headers=headers, json=body
    )
    assert repeated.json() == current
    provider = QuestionProvider()
    await run_one(
        pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, provider, Settings())}
    )
    assert len(provider.contexts) == 1


async def test_selection_drives_question_instead_of_first_page_block(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    material = page()
    material["blocks"] = [
        {
            "id": "b0",
            "heading": "Unrelated introduction",
            "text": "This introduction is unrelated to the selected mechanism.",
            "selector": "p",
        },
        {"id": "b1", "heading": "BPE", "text": SOURCE, "selector": "p.bpe"},
    ]
    material["selection"] = {"block_id": "b1", "quote": SOURCE}
    session = await create(client, headers, page=material)
    await run_one(pg.factory, {"TUTOR_GUIDE": tutor_handler(pg.factory)})
    pending = await request_question(client, headers, session.id)
    provider = QuestionProvider()
    provider.responses["concept_question"]["block_id"] = "b1"
    await run_one(
        pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, provider, Settings())}
    )
    assert json.loads(provider.contexts[0].untrusted_text)["block_id"] == "b1"
    ready = (await client.get(f"/api/v1/assessments/{pending['id']}", headers=headers)).json()
    assert ready["job"]["status"] == "SUCCEEDED"


async def test_recovery_limits_consent_ownership_late_worker_and_answer_protection(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    other = await authenticate(client, "recovery-other")
    await consent(client, headers, True)
    sid = await prepare(client, pg, headers)
    initial = await request_question(client, headers, sid)
    slow = QuestionProvider(blocking=True)
    task = asyncio.create_task(
        run_one(pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, slow, Settings())})
    )
    await asyncio.wait_for(slow.started.wait(), timeout=10)
    await client.post(f"/api/v1/jobs/{initial['job']['id']}/cancel", headers=headers)
    url = f"/api/v1/assessments/{initial['id']}/regenerate"
    body = {"version": initial["version"], "cloud_processing_allowed": True}
    assert (await client.post(url, headers=other, json=body)).status_code == 404
    await consent(client, headers, False)
    assert (await client.post(url, headers=headers, json=body)).status_code == 403
    await consent(client, headers, True)
    recovered = (await client.post(url, headers=headers, json=body)).json()
    slow.release.set()
    await task
    assert (await client.get(f"/api/v1/assessments/{initial['id']}", headers=headers)).json()[
        "question"
    ]["options"] == {}
    failed_provider = QuestionProvider()
    failed_provider.responses["concept_question"]["quote"] = "A forged source quote cannot be used."
    await run_one(
        pg.factory,
        {"ASSESSMENT_QUESTION": concept_handler(pg.factory, failed_provider, Settings())},
    )
    assert (
        await client.post(f"/api/v1/jobs/{recovered['job']['id']}/retry", headers=headers)
    ).json()["code"] == "ASSESSMENT_RECOVERY_REQUIRED"
    third = (
        await client.post(url, headers=headers, json={**body, "version": recovered["version"]})
    ).json()
    good = QuestionProvider()
    await run_one(
        pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, good, Settings())}
    )
    ready = (await client.get(f"/api/v1/assessments/{initial['id']}", headers=headers)).json()
    assert ready["job"]["id"] == third["job"]["id"] and ready["job"]["status"] == "SUCCEEDED"
    answered = await client.post(
        f"/api/v1/assessments/{initial['id']}/answer",
        headers=headers,
        json={"version": ready["version"], "choice": "C"},
    )
    assert answered.status_code == 200
    assert (
        await client.post(
            url, headers=headers, json={**body, "version": answered.json()["version"]}
        )
    ).status_code == 409
    assert (
        await client.delete(f"/api/v1/sessions/{sid}?confirm=true", headers=headers)
    ).status_code == 204
    async with pg.factory() as db:
        assert list(await db.scalars(select(Job))) == []


async def test_cancelled_attempts_are_bounded_and_expired_job_is_replaced(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    from datetime import UTC, datetime, timedelta

    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    current = await request_question(client, headers, await prepare(client, pg, headers))
    async with pg.factory.begin() as db:
        old = await db.get(Job, UUID(current["job"]["id"]))
        assert old
        old.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not await run_one(pg.factory, {})
    for index in range(3):
        if index:
            await client.post(f"/api/v1/jobs/{current['job']['id']}/cancel", headers=headers)
        response = await client.post(
            f"/api/v1/assessments/{current['id']}/regenerate",
            headers=headers,
            json={"version": current["version"], "cloud_processing_allowed": True},
        )
        if index == 2:
            assert (
                response.status_code == 409 and response.json()["code"] == "QUESTION_ATTEMPT_LIMIT"
            )
        else:
            assert response.status_code == 200
            assert response.json()["job"]["id"] != current["job"]["id"]
            current = response.json()


async def test_concept_quota_timeout_and_explicit_block_validation(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    sid = await prepare(client, pg, headers)
    invalid = await client.post(
        "/api/v1/assessments",
        headers=headers,
        json={
            "session_id": str(sid),
            "kind": "CONCEPT_CHECK",
            "cloud_processing_allowed": True,
            "block_id": "b9",
        },
    )
    assert invalid.status_code == 422
    provider = QuestionProvider()
    provider.name = "openai_responses"
    handler = concept_handler(pg.factory, provider, Settings(model_user_calls_per_day=1))
    first = await request_question(client, headers, sid)
    await run_one(pg.factory, {"ASSESSMENT_QUESTION": handler})
    second = await request_question(client, headers, await prepare(client, pg, headers))
    await run_one(pg.factory, {"ASSESSMENT_QUESTION": handler})
    failed = (await client.get(f"/api/v1/assessments/{second['id']}", headers=headers)).json()
    assert failed["job"]["error_code"] == "MODEL_DAILY_BUDGET"
    assert len(provider.contexts) == 1
    assert (await client.get(f"/api/v1/assessments/{first['id']}", headers=headers)).json()["job"][
        "status"
    ] == "SUCCEEDED"
    third = await request_question(client, headers, await prepare(client, pg, headers))
    async with pg.factory.begin() as db:
        job = await db.get(Job, UUID(third["job"]["id"]))
        assert job
        job.timeout_seconds = 1  # Fault injection, never used to manufacture learning evidence.
    blocking = QuestionProvider(blocking=True)
    await run_one(
        pg.factory, {"ASSESSMENT_QUESTION": concept_handler(pg.factory, blocking, Settings())}
    )
    timed = (await client.get(f"/api/v1/assessments/{third['id']}", headers=headers)).json()
    assert timed["job"]["error_code"] == "JOB_TIMEOUT" and timed["question"]["options"] == {}


async def test_populated_0010_rollback_preserves_0009_boundary_question(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import text

    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    boundary_session = await prepare(client, pg, headers)
    boundary = await client.post(
        "/api/v1/assessments", headers=headers, json={"session_id": str(boundary_session)}
    )
    concept = await request_question(client, headers, await prepare(client, pg, headers))
    await run_one(
        pg.factory,
        {"ASSESSMENT_QUESTION": concept_handler(pg.factory, QuestionProvider(), Settings())},
    )
    ready = (await client.get(f"/api/v1/assessments/{concept['id']}", headers=headers)).json()
    answered = (
        await client.post(
            f"/api/v1/assessments/{concept['id']}/answer",
            headers=headers,
            json={"version": ready["version"], "choice": "C"},
        )
    ).json()
    await client.post(
        f"/api/v1/assessments/{concept['id']}/confirm",
        headers=headers,
        json={"version": answered["version"], "confirm": True},
    )
    await client.post("/api/v1/artifacts", headers=headers, json={"assessment_id": concept["id"]})

    def migrate(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=Path(__file__).parents[2],
            env={**os.environ, "FRONTIER_DATABASE_URL": pg.url, "FRONTIER_ENV": "test"},
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0

    await asyncio.to_thread(migrate, "downgrade", "0009_real_connections")
    async with pg.factory() as db:
        values = list((await db.execute(text("SELECT id, question FROM assessments"))).all())
        assert len(values) == 1 and str(values[0][0]) == boundary.json()["id"]
        assert set(values[0][1]) <= {"prompt", "excerpt", "block_id", "options", "rubric", "scope"}
        assert await db.scalar(select(KnowledgeEvidence)) is None
    await asyncio.to_thread(migrate, "upgrade", "head")
    await asyncio.to_thread(migrate, "check")
    restored = await client.get(f"/api/v1/assessments/{boundary.json()['id']}", headers=headers)
    assert restored.status_code == 200 and restored.json()["answer"] is None


async def test_explicit_chapter_is_not_misattributed_to_first_goal_priority(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(concept_client)
    await consent(concept_client, headers, True)
    goal = await make_goal(concept_client, headers, title="BPE and MQA", priorities=["BPE", "MQA"])
    material = page()
    material["blocks"] = [
        {"id": "b0", "heading": "BPE", "text": SOURCE, "selector": "p"},
        {
            "id": "b1",
            "heading": "MQA",
            "text": "MQA shares a single key and value head across multiple query heads.",
            "selector": "p.mqa",
        },
    ]
    session = await create(concept_client, headers, goal_id=str(goal.id), page=material)
    await run_one(pg.factory, {"TUTOR_GUIDE": tutor_handler(pg.factory)})
    result = await concept_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={
            "session_id": str(session.id),
            "kind": "CONCEPT_CHECK",
            "cloud_processing_allowed": True,
            "block_id": "b1",
        },
    )
    assert result.status_code == 201
    assert result.json()["question"]["block_id"] == "b1"
    assert result.json()["concept_name"] == "MQA"


async def test_concurrent_recovery_requests_create_only_one_new_job(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    await consent(client, headers, True)
    pending = await request_question(client, headers, await prepare(client, pg, headers))
    await client.post(f"/api/v1/jobs/{pending['job']['id']}/cancel", headers=headers)
    responses = await asyncio.gather(
        *[
            client.post(
                f"/api/v1/assessments/{pending['id']}/regenerate",
                headers=headers,
                json={"version": pending["version"], "cloud_processing_allowed": True},
            )
            for _ in range(2)
        ]
    )
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["job"]["id"] for response in responses}) == 1
    async with pg.factory() as db:
        jobs = list(await db.scalars(select(Job).where(Job.kind == "ASSESSMENT_QUESTION")))
        assert len(jobs) == 2  # Original terminal job plus one explicit recovery.
