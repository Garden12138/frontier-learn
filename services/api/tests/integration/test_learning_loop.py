from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from app.domain.planning_types import PlanDocument
from app.domain.tutor import tutor_handler
from app.jobs.service import run_one
from app.persistence.models import (
    Assessment,
    KnowledgeEvidence,
    KnowledgeState,
    LearningPlanRevision,
)
from tests.conftest import TestDatabase
from tests.planning_fixture import authenticate, generate, make_goal
from tests.test_citations import create


async def assessed(
    client: AsyncClient,
    pg: TestDatabase,
    headers: dict[str, str],
    goal_id: UUID | None = None,
    choice: str = "B",
) -> dict[str, object]:
    session = await create(client, headers, **({"goal_id": str(goal_id)} if goal_id else {}))
    assert await run_one(pg.factory, {"TUTOR_GUIDE": tutor_handler(pg.factory)})
    created = await client.post(
        "/api/v1/assessments", headers=headers, json={"session_id": str(session.id)}
    )
    assert created.status_code == 201, created.text
    result = await client.post(
        f"/api/v1/assessments/{created.json()['id']}/answer",
        headers=headers,
        json={"version": 1, "choice": choice},
    )
    assert result.status_code == 200, result.text
    return result.json()  # type: ignore[no-any-return]


async def test_two_sessions_confirmed_evidence_replans_without_mastery(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    goal = await make_goal(client, headers, title="Attention")
    plan = await generate(client, headers, goal)
    first = await assessed(client, pg, headers, goal.id)
    assert isinstance(first["feedback"], dict) and first["feedback"]["answered_at"] is not None
    async with pg.factory() as db:
        assert (
            await db.scalar(select(KnowledgeEvidence).where(KnowledgeEvidence.kind == "ASSESSED"))
            is None
        )
    for _ in range(2):
        result = await client.post(
            f"/api/v1/assessments/{first['id']}/confirm",
            headers=headers,
            json={"version": 2, "confirm": True},
        )
        assert result.status_code == 200, result.text
        assert result.json()["plan_revision"] == 2
    second = await assessed(client, pg, headers, goal.id, "A")
    confirmed = await client.post(
        f"/api/v1/assessments/{second['id']}/confirm",
        headers=headers,
        json={"version": 2, "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["plan_revision"] == 3
    async with pg.factory() as db:
        state = await db.scalar(select(KnowledgeState))
        assert state and state.level == "EXPOSED" and state.confidence == "LOW"
        evidence = list(
            await db.scalars(select(KnowledgeEvidence).where(KnowledgeEvidence.kind == "ASSESSED"))
        )
        assert len(evidence) == 2
        revisions = list(
            await db.scalars(
                select(LearningPlanRevision)
                .where(LearningPlanRevision.plan_id == plan.id)
                .order_by(LearningPlanRevision.revision_no)
            )
        )
        assert PlanDocument.model_validate(revisions[1].document).tasks[0].kind == "CHECK"
        assert PlanDocument.model_validate(revisions[2].document).tasks[0].kind == "REVIEW"
        assert str(second["id"]) in revisions[2].rationale


async def test_draft_idempotency_cross_user_and_download_content(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    assessment = await assessed(client, pg, headers)
    response = await client.post(
        "/api/v1/artifacts", headers=headers, json={"assessment_id": assessment["id"]}
    )
    assert response.status_code == 201, response.text
    artifact = response.json()
    assert all(
        title in artifact["markdown"]
        for title in ["来源", "当前理解", "学习步骤", "限制", "未解疑问"]
    )
    repeated = await client.post(
        "/api/v1/artifacts", headers=headers, json={"assessment_id": assessment["id"]}
    )
    assert repeated.json()["id"] == artifact["id"]
    other = await authenticate(client, "other-learner")
    for kind, identity in [("artifacts", artifact["id"]), ("assessments", assessment["id"])]:
        assert (await client.get(f"/api/v1/{kind}/{identity}", headers=other)).status_code == 404
    conflict = await client.put(
        f"/api/v1/artifacts/{artifact['id']}",
        headers=headers,
        json={"version": 100, "markdown": "new"},
    )
    assert conflict.status_code == 409
    rejected = await client.post(
        f"/api/v1/assessments/{assessment['id']}/confirm",
        headers=headers,
        json={"version": 2, "confirm": False},
    )
    assert rejected.status_code == 422
    async with pg.factory() as db:
        row = await db.get(Assessment, UUID(str(assessment["id"])))
        assert row and row.confirmed_at is None


async def test_populated_assessment_rollback_retains_independent_data(
    client: AsyncClient, pg: TestDatabase
) -> None:
    import asyncio
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import inspect

    headers = await authenticate(client)
    assessment = await assessed(client, pg, headers)
    await client.post(
        f"/api/v1/assessments/{assessment['id']}/confirm",
        headers=headers,
        json={"version": 2, "confirm": True},
    )
    await client.post(
        "/api/v1/artifacts", headers=headers, json={"assessment_id": assessment["id"]}
    )
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

    await asyncio.to_thread(migrate, "downgrade", "0006_conversation")
    async with pg.factory() as db:
        connection = await db.connection()
        tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
        assert "assessments" not in tables and "learning_artifacts" not in tables
        assert await db.scalar(select(KnowledgeEvidence)) is None
        state = await db.scalar(select(KnowledgeState))
        assert state and state.level == "UNKNOWN"
    await asyncio.to_thread(migrate, "upgrade", "head")
    assert (
        await client.get(f"/api/v1/sessions/{assessment['session_id']}", headers=headers)
    ).status_code == 200
