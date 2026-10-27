import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.domain.planning_types import GoalInput, GoalResponse, PlanResponse
from app.persistence.models import (
    KnowledgeEvidence,
    LearningPlan,
    LearningPlanRevision,
    TaskCompletion,
)
from tests.conftest import TestDatabase
from tests.github_fixture import GitHubFixture
from tests.integration.test_github_ingest import connect, synchronize
from tests.planning_fixture import authenticate, generate, make_goal


@pytest.mark.parametrize(
    "edges",
    [
        [{"topic": "浇水", "prerequisite": "missing"}],
        [{"topic": "浇水", "prerequisite": "土壤"}, {"topic": "土壤", "prerequisite": "浇水"}],
        [{"topic": "浇水", "prerequisite": "浇水"}],
    ],
)
def test_invalid_prerequisites_are_rejected(edges: list[dict[str, str]]) -> None:
    with pytest.raises(ValidationError):
        GoalInput.model_validate(
            {
                "title": "园艺",
                "minutes_per_day": 30,
                "priorities": ["土壤", "浇水"],
                "prerequisite_edges": edges,
            }
        )


@pytest.mark.postgres
async def test_e2e_001_006_no_repository_and_no_self_report_still_plan(client: AsyncClient) -> None:
    headers = await authenticate(client)
    goal = await make_goal(client, headers, priorities=["土壤", "浇水"], minutes=5)
    plan = await generate(client, headers, goal)
    assert plan.goal_snapshot.self_report == "UNKNOWN"
    assert plan.engine == "LOCAL_RULES"
    assert len(plan.roadmap) == 2 and len(plan.stages) >= 3
    today = [task for task in plan.tasks if task.id in plan.today_task_ids]
    assert today and sum(task.estimated_minutes for task in today) <= 5
    assert all(task.why and task.instruction and "规则建议" in task.why for task in plan.tasks)
    assert plan.sources == []
    assert (await client.get("/api/v1/knowledge", headers=headers)).json() == []


@pytest.mark.postgres
async def test_note_is_a_check_and_recent_assessments_change_next_plan(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    await synchronize(
        client,
        pg,
        headers,
        source.id,
        GitHubFixture({"BPE.md": b"# BPE\n\nNotes only, no verified mastery."}),
    )
    goal = await make_goal(client, headers, title="理解 BPE", priorities=["BPE"])
    first = await generate(client, headers, goal)
    assert first.tasks[0].kind == "CHECK"
    assert first.sources and all(item.available for item in first.sources)
    concept = first.tasks[0].concept_ids[0]
    user_id = (await client.get("/api/v1/auth/me", headers=headers)).json()["id"]
    from uuid import UUID

    positive_id = uuid4()
    async with pg.factory.begin() as db:
        db.add(
            KnowledgeEvidence(
                id=positive_id,
                user_id=UUID(user_id),
                concept_id=concept,
                kind="ASSESSED",
                assessment_id=uuid4(),
                polarity="POSITIVE",
                reliability="MEDIUM",
                method="RUBRIC",
                observed_at=datetime.now(UTC) - timedelta(minutes=1),
                source_locator={"provider": "assessment"},
                excerpt="Synthetic recorded rubric result",
            )
        )
    second = await generate(client, headers, goal, first.revision_no)
    assert second.tasks[0].kind == "APPLY"
    assert positive_id in second.tasks[0].evidence_ids
    assert "理解验证" in second.tasks[0].why
    negative_id = uuid4()
    async with pg.factory.begin() as db:
        db.add(
            KnowledgeEvidence(
                id=negative_id,
                user_id=UUID(user_id),
                concept_id=concept,
                kind="ASSESSED",
                assessment_id=uuid4(),
                polarity="NEGATIVE",
                method="RUBRIC",
                observed_at=datetime.now(UTC),
                source_locator={"provider": "assessment"},
                excerpt="Synthetic later gap",
            )
        )
    third = await generate(client, headers, goal, second.revision_no)
    assert third.tasks[0].kind == "REVIEW" and negative_id in third.tasks[0].evidence_ids
    before = await client.get(f"/api/v1/plans/{first.id}/revisions/1", headers=headers)
    assert before.json()["tasks"][0]["kind"] == "CHECK"
    await client.delete(f"/api/v1/sources/{source.id}?delete_derived=true", headers=headers)
    old = PlanResponse.model_validate(
        (await client.get(f"/api/v1/plans/{first.id}/revisions/1", headers=headers)).json()
    )
    assert old.sources and all(not item.available and item.url is None for item in old.sources)


@pytest.mark.postgres
async def test_goal_edit_creation_idempotency_and_concurrent_generation(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    key = str(uuid4())
    body = {"title": "AI Agent", "minutes_per_day": 30}
    first = await client.post(
        "/api/v1/goals", headers={**headers, "Idempotency-Key": key}, json=body
    )
    repeated = await client.post(
        "/api/v1/goals", headers={**headers, "Idempotency-Key": key}, json=body
    )
    assert first.json()["id"] == repeated.json()["id"]
    conflict = await client.post(
        "/api/v1/goals",
        headers={**headers, "Idempotency-Key": key},
        json={**body, "title": "Changed"},
    )
    assert conflict.status_code == 409
    goal = GoalResponse.model_validate(first.json())
    request = {"goal_id": str(goal.id), "goal_version": goal.version, "expected_revision_no": 0}
    results = await asyncio.gather(
        client.post("/api/v1/plans:generate", headers=headers, json=request),
        client.post("/api/v1/plans:generate", headers=headers, json=request),
    )
    assert sorted(response.status_code for response in results) == [200, 409]
    edit = {**body, "minutes_per_day": 15, "version": goal.version}
    updated = await client.put(f"/api/v1/goals/{goal.id}", headers=headers, json=edit)
    assert updated.status_code == 200 and updated.json()["version"] == goal.version + 1
    assert (
        await client.put(f"/api/v1/goals/{goal.id}", headers=headers, json=edit)
    ).status_code == 409
    plans = (await client.get(f"/api/v1/plans?goal_id={goal.id}", headers=headers)).json()
    assert plans[0]["goal_changed"] is True
    async with pg.factory() as db:
        assert await db.scalar(select(func.count()).select_from(LearningPlan)) == 1
        assert await db.scalar(select(func.count()).select_from(LearningPlanRevision)) == 1


@pytest.mark.postgres
async def test_revisions_skip_pause_interest_reorder_and_restore(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    goal = await make_goal(client, headers)
    plan = await generate(client, headers, goal)
    original_document: dict[str, object]
    async with pg.factory() as db:
        row = await db.scalar(select(LearningPlanRevision))
        assert row is not None
        original_document = row.document

    async def action(name: str, **values: object) -> PlanResponse:
        nonlocal plan
        response = await client.post(
            f"/api/v1/plans/{plan.id}/actions",
            headers=headers,
            json={"revision_no": plan.revision_no, "action": name, **values},
        )
        assert response.status_code == 200, response.text
        plan = PlanResponse.model_validate(response.json())
        return plan

    await action("ACCEPT")
    await action("SKIP", task_id=str(plan.tasks[0].id))
    assert plan.tasks[0].status == "SKIPPED" and plan.today_task_ids
    await action("PAUSE")
    assert plan.today_task_ids == []
    await action("RESUME")
    await action(
        "INSERT",
        interest={
            "title": "临时学习陶艺",
            "estimated_minutes": 5,
            "material_url": "https://example.org/material",
        },
    )
    interest = plan.tasks[0]
    assert interest.origin == "USER"
    order = [str(task.id) for task in plan.tasks[1:]] + [str(interest.id)]
    await action("REORDER", ordered_task_ids=order)
    assert plan.tasks[-1].id == interest.id
    invalid = await client.post(
        f"/api/v1/plans/{plan.id}/actions",
        headers=headers,
        json={
            "revision_no": plan.revision_no,
            "action": "REORDER",
            "ordered_task_ids": list(reversed(order)),
        },
    )
    assert invalid.status_code == 400
    restored = await action("RESTORE", restore_revision_no=1)
    assert restored.tasks[0].status == "PROPOSED" and all(
        task.origin != "USER" for task in restored.tasks
    )
    async with pg.factory() as db:
        row = await db.scalar(
            select(LearningPlanRevision).where(LearningPlanRevision.revision_no == 1)
        )
        assert row is not None and row.document == original_document


@pytest.mark.postgres
async def test_completion_does_not_prove_mastery_or_double_charge_after_restore(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    goal = await make_goal(client, headers)
    plan = await generate(client, headers, goal)
    task = plan.tasks[0]
    completed = await client.post(
        f"/api/v1/plans/{plan.id}/actions",
        headers=headers,
        json={"revision_no": 1, "action": "COMPLETE", "task_id": str(task.id)},
    )
    assert completed.status_code == 200
    assert completed.json()["today_completed_minutes"] == task.estimated_minutes
    restored = await client.post(
        f"/api/v1/plans/{plan.id}/actions",
        headers=headers,
        json={"revision_no": 2, "action": "RESTORE", "restore_revision_no": 1},
    )
    assert restored.status_code == 200
    again = await client.post(
        f"/api/v1/plans/{plan.id}/actions",
        headers=headers,
        json={"revision_no": 3, "action": "COMPLETE", "task_id": str(task.id)},
    )
    assert (
        again.status_code == 200
        and again.json()["today_completed_minutes"] == task.estimated_minutes
    )
    assert (await client.get("/api/v1/knowledge", headers=headers)).json() == []
    async with pg.factory() as db:
        assert await db.scalar(select(func.count()).select_from(KnowledgeEvidence)) == 0
        assert await db.scalar(select(func.count()).select_from(TaskCompletion)) == 1


@pytest.mark.postgres
async def test_goal_and_plan_routes_enforce_owner_and_user_self_report_is_unverified(
    client: AsyncClient,
) -> None:
    headers = await authenticate(client)
    response = await client.post(
        "/api/v1/goals",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "title": "园艺",
            "minutes_per_day": 30,
            "self_report": "PROFICIENT",
            "self_report_reason": "用户自报，未验证",
        },
    )
    goal = GoalResponse.model_validate(response.json())
    plan = await generate(client, headers, goal)
    assert plan.tasks[0].kind == "CHECK" and plan.sources == []
    other = await authenticate(client, "other-planner")
    for method, path, body in [
        ("GET", f"/plans/{plan.id}", None),
        ("GET", f"/plans/{plan.id}/revisions", None),
        ("GET", f"/plans/{plan.id}/revisions/1", None),
        ("GET", f"/plans?goal_id={goal.id}", None),
        ("POST", f"/plans/{plan.id}/actions", {"revision_no": 1, "action": "PAUSE"}),
        ("POST", "/plans:generate", {"goal_id": str(goal.id), "goal_version": 1}),
        ("PUT", f"/goals/{goal.id}", {"title": "other", "minutes_per_day": 30, "version": 1}),
        ("DELETE", f"/goals/{goal.id}?confirm=true", None),
    ]:
        denied = await client.request(method, f"/api/v1{path}", headers=other, json=body)
        assert denied.status_code == 404
    assert (await client.get("/api/v1/goals", headers=other)).json() == []
    assert (await client.get("/api/v1/plans", headers=other)).json() == []
