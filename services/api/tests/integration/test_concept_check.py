import asyncio
import json
from collections.abc import AsyncIterator
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


async def request_question(
    client: AsyncClient, headers: dict[str, str], session_id: UUID
) -> dict[str, object]:
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
    return response.json()  # type: ignore[no-any-return]


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
