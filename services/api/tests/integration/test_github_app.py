from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.connectors.github import GitHubConnector
from app.connectors.github_app import GitHubAppClient
from app.core.security import TokenVault
from app.domain.knowledge_sync import sync_handler
from app.ingestion.http_reader import ReadResponse
from app.jobs.service import run_one
from app.main import create_app
from app.persistence.models import GitHubConnection
from tests.conftest import TestDatabase
from tests.github_app_fixture import AppFixture, app_settings
from tests.github_fixture import GitHubFixture
from tests.planning_fixture import authenticate


@dataclass
class AppContext:
    client: AsyncClient
    app: FastAPI
    remote: AppFixture
    headers: dict[str, str]


@pytest.fixture
async def github_context(pg: TestDatabase) -> AsyncIterator[AppContext]:
    settings = app_settings(pg.url)
    app = create_app(settings)
    remote = AppFixture(settings)
    app.state.github_app_transport = remote
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost:8000"
        ) as connection:
            headers = await authenticate(connection)
            yield AppContext(connection, app, remote, headers)


async def authorize(ctx: AppContext) -> str:
    response = await ctx.client.post("/api/v1/github/authorize", headers=ctx.headers)
    assert response.status_code == 200, response.text
    url = response.json()["authorization_url"]
    assert isinstance(url, str)
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"]
    ctx.remote.expected_challenge = query["code_challenge"][0]
    assert (
        "HttpOnly" in response.headers["set-cookie"]
        and "SameSite=lax" in response.headers["set-cookie"]
    )
    return query["state"][0]


async def connected(ctx: AppContext) -> None:
    state = await authorize(ctx)
    result = await ctx.client.get(
        "/api/v1/github/callback", params={"state": state, "code": "fixture-code"}
    )
    assert result.status_code == 303, result.text
    assert result.headers["location"] == "http://localhost:5173/?github=connected"
    assert "ghu_" not in result.text


async def connect_source(ctx: AppContext) -> str:
    result = await ctx.client.post(
        "/api/v1/github/sources",
        headers=ctx.headers,
        json={
            "installation_id": 7,
            "repository_id": 101,
            "repository": "sample/private-notes",
            "confirm": True,
        },
    )
    assert result.status_code == 201, result.text
    assert result.json()["write_scope"] == []
    return str(result.json()["id"])


async def test_oauth_pkce_browser_state_one_use_and_cookie_isolation(
    github_context: AppContext,
) -> None:
    ctx = github_context
    state = await authorize(ctx)
    cookie = ctx.client.cookies.get("frontier_github_browser")
    ctx.client.cookies.clear()
    refused = await ctx.client.get(
        "/api/v1/github/callback", params={"state": state, "code": "fixture-code"}
    )
    assert refused.status_code == 403 and not ctx.remote.events
    assert cookie
    ctx.client.cookies.set("frontier_github_browser", cookie, path="/api/v1/github/callback")
    result = await ctx.client.get(
        "/api/v1/github/callback", params={"state": state, "code": "fixture-code"}
    )
    assert result.status_code == 303
    replay = await ctx.client.get(
        "/api/v1/github/callback", params={"state": state, "code": "fixture-code"}
    )
    assert replay.status_code == 403


async def test_app_read_write_intersection_sync_and_revoke(
    github_context: AppContext, pg: TestDatabase
) -> None:
    ctx = github_context
    await connected(ctx)
    installations = await ctx.client.get("/api/v1/github/installations", headers=ctx.headers)
    assert installations.json()["items"][0]["id"] == 7
    repos = await ctx.client.get("/api/v1/github/installations/7/repositories", headers=ctx.headers)
    assert repos.json()["items"][0]["id"] == 101
    source = await connect_source(ctx)
    assert ctx.remote.scope_requests[-1]["permissions"] == {"contents": "read", "metadata": "read"}
    denied = await ctx.client.put(
        f"/api/v1/github/sources/{source}/write-permission",
        headers=ctx.headers,
        json={"version": 1, "confirm": False, "path_prefixes": ["notes"]},
    )
    assert denied.status_code == 422
    ctx.remote.push = False
    denied = await ctx.client.put(
        f"/api/v1/github/sources/{source}/write-permission",
        headers=ctx.headers,
        json={"version": 1, "confirm": True, "path_prefixes": ["notes"]},
    )
    assert denied.status_code == 403
    ctx.remote.push = True
    grant = await ctx.client.put(
        f"/api/v1/github/sources/{source}/write-permission",
        headers=ctx.headers,
        json={"version": 1, "confirm": True, "path_prefixes": ["notes"]},
    )
    assert grant.status_code == 204, grant.text
    assert ctx.remote.scope_requests[-1]["permissions"] == {
        "contents": "write",
        "metadata": "read",
        "pull_requests": "write",
    }
    await ctx.client.post(
        f"/api/v1/sources/{source}/sync",
        headers={**ctx.headers, "Idempotency-Key": "app-sync-fixture"},
    )
    reader = GitHubFixture(
        {"notes/learning.md": b"# Attention\n\nA synthetic private learning note."}
    )

    def connector(repo: str, token: object) -> GitHubConnector:
        from pydantic import SecretStr

        assert isinstance(token, SecretStr) and token.get_secret_value() == "ghs_fixture_read"
        return GitHubConnector(repo, token, reader)

    assert await run_one(
        pg.factory,
        {
            "GITHUB_SYNC": sync_handler(
                pg.factory,
                ctx.remote.settings,
                connector,
                lambda: GitHubAppClient(ctx.remote.settings, ctx.remote),
            )
        },
    )
    export = await ctx.client.get("/api/v1/settings/export", headers=ctx.headers)
    assert export.status_code == 200
    assert all(
        secret not in export.text
        for secret in ("ghu_fixture", "ghr_fixture", "ghs_fixture", "encrypted_token")
    )
    other = await authenticate(ctx.client, "another-app-user")
    assert (await ctx.client.get("/api/v1/github/status", headers=other)).json()[
        "connected"
    ] is False
    assert (
        await ctx.client.put(
            f"/api/v1/github/sources/{source}/write-permission",
            headers=other,
            json={"version": 2, "confirm": True, "path_prefixes": ["notes"]},
        )
    ).status_code == 404
    assert (
        await ctx.client.delete("/api/v1/github/connection", headers=ctx.headers)
    ).status_code == 204
    sources = (await ctx.client.get("/api/v1/sources", headers=ctx.headers)).json()
    assert sources[0]["status"] == "DISCONNECTED" and sources[0]["write_scope"] == []
    await connected(ctx)
    assert await connect_source(ctx) == source


async def test_refresh_commits_before_later_repo_failure(
    github_context: AppContext, pg: TestDatabase
) -> None:
    ctx = github_context
    await connected(ctx)
    async with pg.factory.begin() as db:
        row = await db.scalar(select(GitHubConnection))
        assert row
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    ctx.remote.fail_repo = True
    failure = await ctx.client.post(
        "/api/v1/github/sources",
        headers=ctx.headers,
        json={
            "installation_id": 7,
            "repository_id": 101,
            "repository": "sample/private-notes",
            "confirm": True,
        },
    )
    assert failure.status_code == 503
    async with pg.factory() as db:
        row = await db.scalar(select(GitHubConnection))
        assert row and row.encrypted_refresh
        assert (
            TokenVault(ctx.remote.settings.encryption_key)
            .decrypt(row.encrypted_refresh)
            .get_secret_value()
            == "ghr_fixture_new"
        )
    ctx.remote.fail_repo = False
    await connect_source(ctx)


async def test_app_approved_pr_uses_write_token_and_revoke_cancels_pending(
    github_context: AppContext, pg: TestDatabase
) -> None:
    from uuid import uuid4

    from app.domain.writeback import writeback_handler
    from tests.integration.test_learning_loop import assessed
    from tests.writeback_fixture import WriteFixture

    ctx = github_context
    await connected(ctx)
    source = await connect_source(ctx)
    granted = await ctx.client.put(
        f"/api/v1/github/sources/{source}/write-permission",
        headers=ctx.headers,
        json={"version": 1, "confirm": True, "path_prefixes": ["notes"]},
    )
    assert granted.status_code == 204

    class ScopedWriteFixture(WriteFixture):
        async def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            max_bytes: int,
            content: bytes = b"",
        ) -> ReadResponse:
            assert headers["Authorization"] == "Bearer ghs_fixture_write"
            return await super().request(
                method, url, headers=headers, max_bytes=max_bytes, content=content
            )

    write = ScopedWriteFixture("sample/private-notes")
    ctx.app.state.write_transport = write
    for index in range(2):
        assessment = await assessed(ctx.client, pg, ctx.headers)
        artifact = (
            await ctx.client.post(
                "/api/v1/artifacts", headers=ctx.headers, json={"assessment_id": assessment["id"]}
            )
        ).json()
        preview = await ctx.client.post(
            f"/api/v1/artifacts/{artifact['id']}/preview",
            headers=ctx.headers,
            json={"version": 1, "source_id": source, "path": f"notes/learn-{index}.md"},
        )
        assert preview.status_code == 200, preview.text
        approval = await ctx.client.post(
            f"/api/v1/artifacts/{artifact['id']}/approve",
            headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
            json={"version": 2, "confirm": True},
        )
        assert approval.status_code == 202, approval.text
        handlers = {
            "GITHUB_WRITEBACK": writeback_handler(
                pg.factory,
                ctx.remote.settings,
                lambda: write,
                lambda: GitHubAppClient(ctx.remote.settings, ctx.remote),
            )
        }
        if index == 0:
            assert await run_one(pg.factory, handlers)
            job = (
                await ctx.client.get("/api/v1/jobs/" + approval.json()["id"], headers=ctx.headers)
            ).json()
            assert job["status"] == "SUCCEEDED" and len(write.pulls) == 1
        else:
            await ctx.client.delete("/api/v1/github/connection", headers=ctx.headers)
            assert not await run_one(pg.factory, handlers)
            job = (
                await ctx.client.get("/api/v1/jobs/" + approval.json()["id"], headers=ctx.headers)
            ).json()
            assert job["status"] == "CANCELLED" and len(write.pulls) == 1


async def test_revoked_login_cannot_finish_oauth(github_context: AppContext) -> None:
    ctx = github_context
    state = await authorize(ctx)
    assert (await ctx.client.post("/api/v1/auth/logout", headers=ctx.headers)).status_code == 204
    result = await ctx.client.get(
        "/api/v1/github/callback", params={"state": state, "code": "fixture-code"}
    )
    assert result.status_code == 401 and not ctx.remote.events


async def test_disconnect_wins_over_an_already_started_callback(github_context: AppContext) -> None:
    import asyncio

    ctx = github_context
    state = await authorize(ctx)
    ctx.remote.pause_exchange = True
    callback = asyncio.create_task(
        ctx.client.get("/api/v1/github/callback", params={"state": state, "code": "fixture-code"})
    )
    await asyncio.wait_for(ctx.remote.exchange_started.wait(), timeout=10)
    assert (
        await ctx.client.delete("/api/v1/github/connection", headers=ctx.headers)
    ).status_code == 204
    ctx.remote.exchange_release.set()
    result = await callback
    assert result.status_code == 403 and result.json()["code"] == "OAUTH_REVOKED"
    assert (await ctx.client.get("/api/v1/github/status", headers=ctx.headers)).json()[
        "connected"
    ] is False
