from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.connectors.github import GitHubConnector
from app.core.config import Settings
from app.domain.knowledge_sync import sync_handler
from app.domain.writeback import writeback_handler
from app.jobs.service import run_one
from app.main import create_app
from app.persistence.models import Job, LearningArtifact, LearningPlanRevision
from tests.conftest import TestDatabase
from tests.github_fixture import GitHubFixture
from tests.integration.test_learning_loop import assessed
from tests.planning_fixture import authenticate, generate, make_goal
from tests.writeback_fixture import WriteFixture


@dataclass
class WriteContext:
    client: AsyncClient
    settings: Settings
    remote: WriteFixture
    headers: dict[str, str]
    source_id: str
    artifact: dict[str, object]


@pytest.fixture
async def write_context(pg: TestDatabase) -> AsyncIterator[WriteContext]:
    settings = Settings(
        env="test",
        database_url=SecretStr(pg.url),
        mock_auth=True,
        writeback_enabled=True,
        encryption_key=SecretStr(Fernet.generate_key().decode()),
    )
    app = create_app(settings)
    remote = WriteFixture()
    app.state.write_transport = remote
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = await authenticate(client)
            source = await client.post(
                "/api/v1/sources",
                headers=headers,
                json={"external_ref": "sample/notes", "consent": True},
            )
            source_id = source.json()["id"]
            granted = await client.put(
                f"/api/v1/sources/{source_id}/write-permission",
                headers=headers,
                json={
                    "version": 1,
                    "confirm": True,
                    "credential": "fixture-write-secret",
                    "path_prefixes": ["notes"],
                },
            )
            assert granted.status_code == 204, granted.text
            goal = await make_goal(client, headers, title="Attention")
            await generate(client, headers, goal)
            assessment = await assessed(client, pg, headers, goal.id)
            await client.post(
                f"/api/v1/assessments/{assessment['id']}/confirm",
                headers=headers,
                json={"version": 2, "confirm": True},
            )
            response = await client.post(
                "/api/v1/artifacts", headers=headers, json={"assessment_id": assessment["id"]}
            )
            assert response.status_code == 201, response.text
            yield WriteContext(client, settings, remote, headers, source_id, response.json())


async def preview(
    ctx: WriteContext, path: str = "notes/learning.md", mode: str = "NEW"
) -> dict[str, object]:
    response = await ctx.client.post(
        f"/api/v1/artifacts/{ctx.artifact['id']}/preview",
        headers=ctx.headers,
        json={
            "version": ctx.artifact["version"],
            "source_id": ctx.source_id,
            "path": path,
            "mode": mode,
        },
    )
    assert response.status_code == 200, response.text
    ctx.artifact = response.json()
    return ctx.artifact


async def approve(ctx: WriteContext) -> str:
    response = await ctx.client.post(
        f"/api/v1/artifacts/{ctx.artifact['id']}/approve",
        headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
        json={"version": ctx.artifact["version"], "confirm": True},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


async def retry(ctx: WriteContext, pg: TestDatabase, job_id: str) -> None:
    response = await ctx.client.post(f"/api/v1/jobs/{job_id}/retry", headers=ctx.headers)
    assert response.status_code == 200, response.text
    async with pg.factory.begin() as db:
        job = await db.get(Job, UUID(job_id))
        assert job
        job.next_attempt_at = datetime.now(UTC)


@pytest.mark.parametrize("lost", ["pr", "ref"])
async def test_write_approval_and_lost_response_reconciled_once(
    write_context: WriteContext, pg: TestDatabase, lost: str
) -> None:
    ctx = write_context
    no_preview = await ctx.client.post(
        f"/api/v1/artifacts/{ctx.artifact['id']}/approve",
        headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
        json={"version": 1, "confirm": True},
    )
    assert no_preview.status_code == 409
    await preview(ctx)
    assert all(method == "GET" for method, _ in ctx.remote.calls)
    not_confirmed = await ctx.client.post(
        f"/api/v1/artifacts/{ctx.artifact['id']}/approve",
        headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
        json={"version": ctx.artifact["version"], "confirm": False},
    )
    assert not_confirmed.status_code == 422
    job_id = await approve(ctx)
    assert await approve(ctx) == job_id
    ctx.remote.lose_pr_response, ctx.remote.lose_ref_response = lost == "pr", lost == "ref"
    handlers = {"GITHUB_WRITEBACK": writeback_handler(pg.factory, ctx.settings, lambda: ctx.remote)}
    assert await run_one(pg.factory, handlers)
    assert (await ctx.client.get(f"/api/v1/jobs/{job_id}", headers=ctx.headers)).json()[
        "status"
    ] == "FAILED"
    await retry(ctx, pg, job_id)
    assert await run_one(pg.factory, handlers)
    assert (await ctx.client.get(f"/api/v1/jobs/{job_id}", headers=ctx.headers)).json()[
        "status"
    ] == "SUCCEEDED"
    assert len(ctx.remote.pulls) == 1
    assert ctx.remote.calls.count(("POST", "/git/refs")) == 1
    assert ctx.remote.refs["main"] == "a" * 40
    saved = (
        await ctx.client.get(f"/api/v1/artifacts/{ctx.artifact['id']}", headers=ctx.headers)
    ).json()
    assert saved["pr_url"] == "https://github.com/sample/notes/pull/1"
    assert "fixture-write-secret" not in str(saved)


@pytest.mark.parametrize("scenario", ["base", "revoke", "denied"])
async def test_conflict_revocation_and_permission_keep_draft(
    write_context: WriteContext, pg: TestDatabase, scenario: str
) -> None:
    ctx = write_context
    await preview(ctx)
    job_id = await approve(ctx)
    if scenario == "base":
        ctx.remote.refs["main"] = "b" * 40
    elif scenario == "revoke":
        assert (
            await ctx.client.delete(
                f"/api/v1/sources/{ctx.source_id}/write-permission", headers=ctx.headers
            )
        ).status_code == 204
    else:
        ctx.remote.denied = True
    assert await run_one(
        pg.factory,
        {"GITHUB_WRITEBACK": writeback_handler(pg.factory, ctx.settings, lambda: ctx.remote)},
    )
    job = (await ctx.client.get(f"/api/v1/jobs/{job_id}", headers=ctx.headers)).json()
    assert job["status"] == "FAILED"
    assert job["error_code"] in {"WRITE_BASE_CONFLICT", "WRITE_REVOKED", "WRITE_PERMISSION"}
    assert not any(method != "GET" for method, _ in ctx.remote.calls)
    saved = (
        await ctx.client.get(f"/api/v1/artifacts/{ctx.artifact['id']}", headers=ctx.headers)
    ).json()
    assert saved["markdown"] == ctx.artifact["markdown"]
    if scenario == "base":
        await preview(ctx)
        assert await approve(ctx) != job_id


async def test_merged_pr_reindexes_and_replans_once(
    write_context: WriteContext, pg: TestDatabase
) -> None:
    ctx = write_context
    await preview(ctx)
    await approve(ctx)
    assert await run_one(
        pg.factory,
        {"GITHUB_WRITEBACK": writeback_handler(pg.factory, ctx.settings, lambda: ctx.remote)},
    )
    body = {"version": ctx.artifact["version"], "confirm": True}
    endpoint = f"/api/v1/artifacts/{ctx.artifact['id']}/reindex"
    assert (await ctx.client.post(endpoint, headers=ctx.headers, json=body)).status_code == 409
    pull = ctx.remote.pulls[0]
    pull["merged"], pull["merge_commit_sha"] = True, "c" * 40
    ctx.remote.files[("c" * 40, "notes/learning.md")] = str(ctx.artifact["markdown"])
    request = await ctx.client.post(endpoint, headers=ctx.headers, json=body)
    assert request.status_code == 202, request.text
    reader = GitHubFixture({"notes/learning.md": str(ctx.artifact["markdown"]).encode()})
    assert await run_one(
        pg.factory,
        {
            "GITHUB_SYNC": sync_handler(
                pg.factory, ctx.settings, lambda repo, token: GitHubConnector(repo, token, reader)
            )
        },
    )
    async with pg.factory() as db:
        artifact = await db.get(LearningArtifact, UUID(str(ctx.artifact["id"])))
        assert artifact and artifact.reindexed_at
        revisions = list(
            await db.scalars(
                select(LearningPlanRevision).order_by(LearningPlanRevision.revision_no)
            )
        )
        assert len(revisions) == 3 and "已重新索引" in revisions[-1].rationale
    second = await ctx.client.post(endpoint, headers=ctx.headers, json=body)
    assert second.status_code == 202 and second.json()["id"] == request.json()["id"]


@pytest.mark.parametrize(
    "path", ["../notes/x.md", ".github/workflows/x.md", "other/x.md", "notes/x.py"]
)
async def test_write_scope_cannot_escape(write_context: WriteContext, path: str) -> None:
    ctx = write_context
    response = await ctx.client.post(
        f"/api/v1/artifacts/{ctx.artifact['id']}/preview",
        headers=ctx.headers,
        json={"version": ctx.artifact["version"], "source_id": ctx.source_id, "path": path},
    )
    assert response.status_code in {400, 403}
    assert not ctx.remote.calls


async def test_expired_write_permission_requires_new_diff_approval(
    write_context: WriteContext, pg: TestDatabase
) -> None:
    ctx = write_context
    await preview(ctx)
    job_id = await approve(ctx)
    ctx.remote.denied = True
    handlers = {"GITHUB_WRITEBACK": writeback_handler(pg.factory, ctx.settings, lambda: ctx.remote)}
    await run_one(pg.factory, handlers)
    ctx.remote.denied = False
    grant = await ctx.client.put(
        f"/api/v1/sources/{ctx.source_id}/write-permission",
        headers=ctx.headers,
        json={
            "version": 2,
            "confirm": True,
            "credential": "renewed-fixture-secret",
            "path_prefixes": ["notes"],
        },
    )
    assert grant.status_code == 204
    assert (
        await ctx.client.post(f"/api/v1/jobs/{job_id}/retry", headers=ctx.headers)
    ).status_code == 409
    await preview(ctx)
    assert await approve(ctx) != job_id
    await run_one(pg.factory, handlers)
    assert len(ctx.remote.pulls) == 1
    assert ctx.remote.refs["main"] == "a" * 40


async def test_manual_merge_and_stale_approval(
    write_context: WriteContext, pg: TestDatabase
) -> None:
    ctx = write_context
    ctx.remote.files[("a" * 40, "notes/existing.md")] = (
        "# Existing note\nKeep this independent material.\n"
    )
    endpoint = f"/api/v1/artifacts/{ctx.artifact['id']}"
    conflict = await ctx.client.post(
        endpoint + "/preview",
        headers=ctx.headers,
        json={"version": 1, "source_id": ctx.source_id, "path": "notes/existing.md", "mode": "NEW"},
    )
    assert conflict.status_code == 409
    updated = await ctx.client.put(
        endpoint,
        headers=ctx.headers,
        json={
            "version": 1,
            "markdown": "# Existing note\nKeep this independent material.\n\n"
            + str(ctx.artifact["markdown"]),
        },
    )
    assert updated.status_code == 200
    ctx.artifact = updated.json()
    await preview(ctx, "notes/existing.md", "MANUAL_MERGE")
    response = await ctx.client.post(
        endpoint + "/approve",
        headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
        json={"version": 1, "confirm": True},
    )
    assert response.status_code == 409
    await approve(ctx)
    await run_one(
        pg.factory,
        {"GITHUB_WRITEBACK": writeback_handler(pg.factory, ctx.settings, lambda: ctx.remote)},
    )
    assert len(ctx.remote.pulls) == 1
    assert (
        ctx.remote.files[("a" * 40, "notes/existing.md")]
        == "# Existing note\nKeep this independent material.\n"
    )


async def test_cancel_pending_writeback_has_no_remote_effect(
    write_context: WriteContext, pg: TestDatabase
) -> None:
    ctx = write_context
    await preview(ctx)
    job_id = await approve(ctx)
    cancelled = await ctx.client.post(f"/api/v1/jobs/{job_id}/cancel", headers=ctx.headers)
    assert cancelled.status_code == 200
    assert not await run_one(
        pg.factory,
        {"GITHUB_WRITEBACK": writeback_handler(pg.factory, ctx.settings, lambda: ctx.remote)},
    )
    assert ctx.remote.pulls == [] and all(method == "GET" for method, _ in ctx.remote.calls)


async def test_default_branch_change_cannot_redirect_a_write(
    write_context: WriteContext, pg: TestDatabase
) -> None:
    ctx = write_context
    await preview(ctx)
    await approve(ctx)
    assert isinstance(ctx.artifact["preview"], dict)
    branch = str(ctx.artifact["preview"]["branch"])
    ctx.remote.default_branch = branch
    ctx.remote.refs[branch] = ctx.remote.refs["main"]
    await run_one(
        pg.factory,
        {"GITHUB_WRITEBACK": writeback_handler(pg.factory, ctx.settings, lambda: ctx.remote)},
    )
    assert not any(method != "GET" for method, _ in ctx.remote.calls)
    assert ctx.remote.refs[branch] == "a" * 40 and not ctx.remote.pulls


async def test_foreign_changes_on_dedicated_branch_cannot_enter_pr(
    write_context: WriteContext, pg: TestDatabase
) -> None:
    ctx = write_context
    await preview(ctx)
    job_id = await approve(ctx)
    ctx.remote.lose_ref_response = True
    handlers = {"GITHUB_WRITEBACK": writeback_handler(pg.factory, ctx.settings, lambda: ctx.remote)}
    await run_one(pg.factory, handlers)
    assert isinstance(ctx.artifact["preview"], dict)
    branch = str(ctx.artifact["preview"]["branch"])
    original = ctx.remote.commits[ctx.remote.refs[branch]]
    ctx.remote.commits["d" * 40] = {**original, "tree": {"sha": "e" * 40}}
    ctx.remote.refs[branch] = "d" * 40
    await retry(ctx, pg, job_id)
    await run_one(pg.factory, handlers)
    job = (await ctx.client.get(f"/api/v1/jobs/{job_id}", headers=ctx.headers)).json()
    assert job["error_code"] == "WRITE_BRANCH_CONFLICT"
    assert ctx.remote.refs[branch] == "d" * 40 and ctx.remote.pulls == []
    assert not any(method in {"PUT", "PATCH", "DELETE"} for method, _ in ctx.remote.calls)
