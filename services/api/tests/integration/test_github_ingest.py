from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.api.auth import LoginResponse
from app.api.jobs import JobResponse
from app.api.sources import SourceResponse
from app.connectors.github import GitHubConnector
from app.core.config import Settings
from app.domain.knowledge_sync import sync_handler
from app.jobs.service import run_one
from app.persistence.models import KnowledgeEvidence, SourceDocument
from tests.conftest import TestDatabase
from tests.github_fixture import GitHubFixture

pytestmark = pytest.mark.postgres


async def connect(
    client: AsyncClient, repository: str = "learner/notes"
) -> tuple[dict[str, str], SourceResponse]:
    login = LoginResponse.model_validate(
        (await client.post("/api/v1/auth/mock-login", json={"identity": "ingest-user"})).json()
    )
    headers = {"Authorization": f"Bearer {login.access_token}"}
    response = await client.post(
        "/api/v1/sources", headers=headers, json={"external_ref": repository, "consent": True}
    )
    assert response.status_code == 201
    return headers, SourceResponse.model_validate(response.json())


async def synchronize(
    client: AsyncClient,
    pg: TestDatabase,
    headers: dict[str, str],
    source_id: UUID,
    fixture: GitHubFixture,
) -> JobResponse:
    response = await client.post(
        f"/api/v1/sources/{source_id}/sync", headers={**headers, "Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 202
    job = JobResponse.model_validate(response.json())
    handler = sync_handler(
        pg.factory,
        Settings(env="test", database_url=SecretStr(pg.url)),
        lambda repository, token: GitHubConnector(repository, token, fixture),
    )
    assert await run_one(pg.factory, {"GITHUB_SYNC": handler})
    return JobResponse.model_validate(
        (await client.get(f"/api/v1/jobs/{job.id}", headers=headers)).json()
    )


async def test_e2e_002_003_005_profile_citations_and_idempotency(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    fixture = GitHubFixture(
        {
            "BPE.md": b"# BPE\n\nByte pair encoding.",
            "Attention.md": b"# Attention\n\nGQA is mentioned without a quiz.",
            "Agent.md": b"# Agent Memory\n\nRetrieval and memory.",
            "vllm.md": b"# vLLM\n\nDeployment notes.",
            "dist/generated.md": b"ignored",
        }
    )
    first = await synchronize(client, pg, headers, source.id, fixture)
    assert first.status == "SUCCEEDED"
    profile = (await client.get("/api/v1/knowledge", headers=headers)).json()
    assert len(profile) >= 5
    for state in profile:
        assert state["level"] == "EXPOSED"
        assert state["confidence"] == "LOW"
        evidence = (
            await client.get(f"/api/v1/knowledge/{state['concept_id']}/evidence", headers=headers)
        ).json()
        assert evidence
        for item in evidence:
            locator = item["source_locator"]
            assert locator["commit_sha"] == fixture.revision
            assert locator["path"] in fixture.files
            assert f"/blob/{fixture.revision}/" in locator["url"]
            assert item["excerpt"] in fixture.files[locator["path"]].decode()
            source_lines = fixture.files[locator["path"]].decode().splitlines(keepends=True)
            assert item["excerpt"] in "".join(
                source_lines[locator["line_start"] - 1 : locator["line_end"]]
            )
    async with pg.factory() as db:
        before = await db.scalar(select(func.count()).select_from(KnowledgeEvidence))
    blob_reads = len([c for c in fixture.calls if "/git/blobs/" in c])
    assert (await synchronize(client, pg, headers, source.id, fixture)).status == "SUCCEEDED"
    assert len([c for c in fixture.calls if "/git/blobs/" in c]) == blob_reads
    async with pg.factory() as db:
        assert await db.scalar(select(func.count()).select_from(KnowledgeEvidence)) == before
        assert await db.scalar(select(func.count()).select_from(SourceDocument)) == 4


async def test_e2e_004_changes_deletion_rename_and_other_source_preservation(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    fixture = GitHubFixture(
        {"BPE.md": b"# BPE\n\nOriginal note.", "Attention.md": b"# Attention\n\nSource one."}
    )
    assert (await synchronize(client, pg, headers, source.id, fixture)).status == "SUCCEEDED"
    _, other = await connect(client, "learner/other")
    other_fixture = GitHubFixture({"Attention.md": b"# Attention\n\nIndependent source."})
    await synchronize(client, pg, headers, other.id, other_fixture)
    fixture.files = {
        "moved/BPE.md": b"# BPE\n\nOriginal note.",
        "New.md": b"# Algebra\n\nVector spaces.",
    }
    fixture.revision = "c" * 40
    assert (await synchronize(client, pg, headers, source.id, fixture)).status == "SUCCEEDED"
    docs = (await client.get(f"/api/v1/sources/{source.id}/documents", headers=headers)).json()
    renamed = next(d for d in docs if d["path"] == "moved/BPE.md")
    assert renamed["renamed_from"] == "BPE.md"
    profile = (await client.get("/api/v1/knowledge", headers=headers)).json()
    attention = next(s for s in profile if s["name"] == "Attention")
    evidence = (
        await client.get(f"/api/v1/knowledge/{attention['concept_id']}/evidence", headers=headers)
    ).json()
    assert len(evidence) == 1
    assert evidence[0]["source_locator"]["repository"] == "learner/other"
    await client.delete(f"/api/v1/sources/{source.id}?delete_derived=true", headers=headers)
    assert (
        await client.get(f"/api/v1/knowledge/{attention['concept_id']}/evidence", headers=headers)
    ).json() == evidence


async def test_bad_file_partial_retry_and_permission_failure_preserve_data(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    fixture = GitHubFixture({"good.md": b"# BPE\n\nA valid explanation.", "broken.md": b"\xff\xfe"})
    partial = await synchronize(client, pg, headers, source.id, fixture)
    assert partial.status == "PARTIAL"
    assert partial.progress == 1
    assert (await client.get("/api/v1/knowledge", headers=headers)).json()
    docs = (await client.get(f"/api/v1/sources/{source.id}/documents", headers=headers)).json()
    assert next(d for d in docs if d["path"] == "broken.md")["error_code"] == "UNSUPPORTED_ENCODING"
    fixture.files["broken.md"] = b"# Fixed\n\nRecovered text."
    fixture.revision = "d" * 40
    assert (await synchronize(client, pg, headers, source.id, fixture)).status == "SUCCEEDED"
    before = (await client.get("/api/v1/knowledge", headers=headers)).json()
    fixture.status = 403
    denied = await synchronize(client, pg, headers, source.id, fixture)
    assert denied.status == "FAILED" and denied.error_code == "GITHUB_ACCESS_DENIED"
    assert (await client.get("/api/v1/knowledge", headers=headers)).json() == before


async def test_source_and_evidence_api_tenant_isolation_and_cancel(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    fixture = GitHubFixture({"note.md": b"# BPE\n\nNotes."})
    await synchronize(client, pg, headers, source.id, fixture)
    profile = (await client.get("/api/v1/knowledge", headers=headers)).json()
    bob = LoginResponse.model_validate(
        (await client.post("/api/v1/auth/mock-login", json={"identity": "bob"})).json()
    )
    denied_headers = {
        "Authorization": f"Bearer {bob.access_token}",
        "Idempotency-Key": str(uuid4()),
    }
    for method, path in [
        ("POST", f"/sources/{source.id}/sync"),
        ("GET", f"/sources/{source.id}/documents"),
        ("DELETE", f"/sources/{source.id}"),
        ("GET", f"/knowledge/{profile[0]['concept_id']}/evidence"),
    ]:
        assert (
            await client.request(method, f"/api/v1{path}", headers=denied_headers)
        ).status_code == 404
    pending = JobResponse.model_validate(
        (
            await client.post(
                f"/api/v1/sources/{source.id}/sync",
                headers={**headers, "Idempotency-Key": str(uuid4())},
            )
        ).json()
    )
    await client.post(f"/api/v1/jobs/{pending.id}/cancel", headers=headers)
    handler = sync_handler(
        pg.factory,
        Settings(env="test"),
        lambda repository, token: GitHubConnector(repository, token, fixture),
    )
    assert not await run_one(pg.factory, {"GITHUB_SYNC": handler})
    assert (await client.get(f"/api/v1/jobs/{pending.id}", headers=headers)).json()[
        "status"
    ] == "CANCELLED"
