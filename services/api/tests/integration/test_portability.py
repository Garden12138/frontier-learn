import hashlib
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import func, select

from app.jobs.service import run_one
from app.persistence.models import Assessment, Job, KnowledgeEvidence, LearningArtifact, User
from tests.conftest import TestDatabase
from tests.github_fixture import GitHubFixture
from tests.integration.test_learning_loop import assessed
from tests.integration.test_writeback_safety import WriteContext, approve, preview, write_context
from tests.planning_fixture import authenticate, make_goal

__all__ = ["write_context"]


async def test_export_excludes_credentials_and_other_users(write_context: WriteContext) -> None:
    ctx = write_context
    other = await authenticate(ctx.client, "export-other-user")
    await make_goal(ctx.client, other, title="OTHER_PRIVATE_GOAL")
    export = await ctx.client.get("/api/v1/settings/export", headers=ctx.headers)
    assert export.status_code == 200, export.text
    data = export.json()
    assert data["schema_version"] == 1
    assert data["learning_artifacts"][0]["markdown"] == ctx.artifact["markdown"]
    assert len(data["assessments"]) == 1
    assert "fixture-write-secret" not in export.text
    assert "encrypted_write_credential" not in export.text
    assert "token_digest" not in export.text
    assert "OTHER_PRIVATE_GOAL" not in export.text
    assert ctx.headers["Authorization"].removeprefix("Bearer ") not in export.text
    digest = hashlib.sha256(
        ctx.headers["Authorization"].removeprefix("Bearer ").encode()
    ).hexdigest()
    assert digest not in export.text
    foreign = (await ctx.client.get("/api/v1/settings/export", headers=other)).json()
    assert foreign["learning_artifacts"] == [] and foreign["assessments"] == []


async def test_delete_confirmation_cancels_jobs_and_preserves_other_user(
    write_context: WriteContext, pg: TestDatabase
) -> None:
    ctx = write_context
    await preview(ctx)
    await approve(ctx)
    other = await authenticate(ctx.client, "kept-user")
    kept = await make_goal(ctx.client, other, title="Keep my records")
    not_confirmed = await ctx.client.request(
        "DELETE", "/api/v1/settings/data", headers=ctx.headers, json={"confirmation": "wrong"}
    )
    assert not_confirmed.status_code == 422
    assert (await ctx.client.get("/api/v1/auth/me", headers=ctx.headers)).status_code == 200
    deleted = await ctx.client.request(
        "DELETE",
        "/api/v1/settings/data",
        headers=ctx.headers,
        json={"confirmation": "DELETE_MY_DATA"},
    )
    assert deleted.status_code == 204, deleted.text
    assert (await ctx.client.get("/api/v1/auth/me", headers=ctx.headers)).status_code == 401
    remaining = await ctx.client.get("/api/v1/goals", headers=other)
    assert remaining.status_code == 200 and remaining.json()[0]["id"] == str(kept.id)
    assert not await run_one(pg.factory, {})
    async with pg.factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1
        assert await db.scalar(select(func.count()).select_from(LearningArtifact)) == 0
        assert await db.scalar(select(func.count()).select_from(Job)) == 0
    assert ctx.remote.pulls == []


async def test_source_deletion_preserves_independent_sources_and_assessment(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers = await authenticate(client)
    reader = GitHubFixture({"Attention.md": b"# Attention\n\nA synthetic note with a source."})
    from app.api.sources import SourceResponse
    from app.connectors.github import GitHubConnector
    from app.core.config import Settings
    from app.domain.knowledge_sync import sync_handler

    source_ids: list[str] = []
    for repository in ("sample/one", "sample/two"):
        created = await client.post(
            "/api/v1/sources", headers=headers, json={"external_ref": repository, "consent": True}
        )
        source_ids.append(SourceResponse.model_validate(created.json()).id.hex)
        await client.post(
            f"/api/v1/sources/{source_ids[-1]}/sync",
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        assert await run_one(
            pg.factory,
            {
                "GITHUB_SYNC": sync_handler(
                    pg.factory, Settings(), lambda repo, token: GitHubConnector(repo, token, reader)
                )
            },
        )
    source_a, source_b = (UUID(identity) for identity in source_ids)
    assessment = await assessed(client, pg, headers)
    confirmed = await client.post(
        f"/api/v1/assessments/{assessment['id']}/confirm",
        headers=headers,
        json={"version": 2, "confirm": True},
    )
    assert confirmed.status_code == 200
    result = await client.delete(f"/api/v1/sources/{source_a}?delete_derived=true", headers=headers)
    assert result.status_code == 204
    async with pg.factory() as db:
        evidence = list(await db.scalars(select(KnowledgeEvidence)))
        assert any(row.assessment_id == UUID(str(assessment["id"])) for row in evidence)
        assert any(row.document_id is not None for row in evidence)
    data = (await client.get("/api/v1/settings/export", headers=headers)).json()
    assert all(row["source_id"] == str(source_b) for row in data["source_documents"])


async def test_session_deletion_removes_derived_assessment_and_draft(
    client: AsyncClient, pg: TestDatabase
) -> None:
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
    removed = await client.delete(
        f"/api/v1/sessions/{assessment['session_id']}?confirm=true", headers=headers
    )
    assert removed.status_code == 204, removed.text
    async with pg.factory() as db:
        assert await db.scalar(select(func.count()).select_from(Assessment)) == 0
        assert await db.scalar(select(func.count()).select_from(LearningArtifact)) == 0
        assert await db.scalar(select(func.count()).select_from(KnowledgeEvidence)) == 0


async def test_model_consent_default_and_version_conflict(client: AsyncClient) -> None:
    headers = await authenticate(client)
    initial = (await client.get("/api/v1/settings", headers=headers)).json()
    assert initial["cloud_processing_allowed"] is False
    assert initial["active_provider"] == "LOCAL_RULES"
    changed = await client.put(
        "/api/v1/settings",
        headers=headers,
        json={"version": initial["version"], "cloud_processing_allowed": True, "confirm": True},
    )
    assert changed.status_code == 200 and changed.json()["cloud_processing_allowed"] is True
    stale = await client.put(
        "/api/v1/settings",
        headers=headers,
        json={"version": initial["version"], "cloud_processing_allowed": False, "confirm": True},
    )
    assert stale.status_code == 409


async def test_export_limit_fails_without_partial_data(
    client: AsyncClient, monkeypatch: object
) -> None:
    from pytest import MonkeyPatch

    from app.domain import data_portability

    assert isinstance(monkeypatch, MonkeyPatch)
    headers = await authenticate(client)
    await make_goal(client, headers)
    monkeypatch.setattr(data_portability, "MAX_EXPORT_BYTES", 10)
    response = await client.get("/api/v1/settings/export", headers=headers)
    assert response.status_code == 413 and response.json()["code"] == "EXPORT_LIMIT"
    assert "learning_goals" not in response.json()
