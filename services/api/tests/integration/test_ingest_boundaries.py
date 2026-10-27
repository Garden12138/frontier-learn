import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api.jobs import JobResponse
from app.connectors.base import DocumentRef, SourceScope
from app.connectors.github import GitHubConnector
from app.core.config import Settings
from app.domain.knowledge_sync import sync_handler
from app.jobs.service import run_one
from app.persistence.models import SourceDocument
from tests.conftest import TestDatabase
from tests.github_fixture import GitHubFixture
from tests.integration.test_github_ingest import connect, synchronize

pytestmark = pytest.mark.postgres


async def test_folder_selection_and_source_version_conflicts(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    fixture = GitHubFixture(
        {
            "notes/BPE.md": b"# BPE\n\nSelected text.",
            "outside/Attention.md": b"# Attention\n\nOther folder.",
        }
    )
    await synchronize(client, pg, headers, source.id, fixture)
    body = {"version": source.version, "status": "CONNECTED", "path_prefixes": ["notes"]}
    updated = await client.patch(f"/api/v1/sources/{source.id}", headers=headers, json=body)
    assert updated.status_code == 200 and updated.json()["path_prefixes"] == ["notes/"]
    assert (
        await client.patch(f"/api/v1/sources/{source.id}", headers=headers, json=body)
    ).status_code == 409
    await synchronize(client, pg, headers, source.id, fixture)
    states = (await client.get("/api/v1/knowledge", headers=headers)).json()
    outside = next(s for s in states if s["name"] == "Attention")
    assert outside["level"] == "UNKNOWN" and outside["evidence_count"] == 0
    invalid = await client.patch(
        f"/api/v1/sources/{source.id}",
        headers=headers,
        json={**body, "version": updated.json()["version"], "path_prefixes": ["../escape/"]},
    )
    assert invalid.status_code == 422


async def test_manual_correction_version_and_duplicate_material(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    fixture = GitHubFixture(
        {
            "a.md": b"# BPE\n\nEvidence only, not a mastery claim.",
            "duplicate.md": b"# BPE\n\nEvidence only, not a mastery claim.",
        }
    )
    await synchronize(client, pg, headers, source.id, fixture)
    states = (await client.get("/api/v1/knowledge", headers=headers)).json()
    state = next(s for s in states if s["name"] == "BPE")
    assert state["evidence_count"] == 1
    body = {
        "version": state["version"],
        "level": "PROFICIENT",
        "reason": "用户自报，仍需要独立验证",
    }
    corrected = await client.patch(
        f"/api/v1/knowledge/{state['concept_id']}", headers=headers, json=body
    )
    assert corrected.status_code == 200
    assert corrected.json()["confidence"] == "LOW" and corrected.json()["verified_at"] is None
    assert corrected.json()["override_level"] == "PROFICIENT"
    assert (
        await client.patch(f"/api/v1/knowledge/{state['concept_id']}", headers=headers, json=body)
    ).status_code == 409
    await client.delete(f"/api/v1/sources/{source.id}?delete_derived=true", headers=headers)
    evidence = (
        await client.get(f"/api/v1/knowledge/{state['concept_id']}/evidence", headers=headers)
    ).json()
    assert len(evidence) == 1 and evidence[0]["kind"] == "USER_CORRECTION"


async def test_cancel_during_fetch_prevents_late_evidence_commit(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    fixture = GitHubFixture({"note.md": b"# BPE\n\nValid source text."})
    entered, release = asyncio.Event(), asyncio.Event()

    class DelayedGitHub(GitHubConnector):
        async def read_document(self, scope: SourceScope, document: DocumentRef) -> bytes:
            entered.set()
            await release.wait()
            return await super().read_document(scope, document)

    queued = await client.post(
        f"/api/v1/sources/{source.id}/sync", headers={**headers, "Idempotency-Key": str(uuid4())}
    )
    job = JobResponse.model_validate(queued.json())
    handler = sync_handler(
        pg.factory,
        Settings(env="test"),
        lambda repository, token: DelayedGitHub(repository, token, fixture),
    )
    task = asyncio.create_task(run_one(pg.factory, {"GITHUB_SYNC": handler}))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        await client.post(f"/api/v1/jobs/{job.id}/cancel", headers=headers)
    finally:
        release.set()
        await task
    assert (await client.get("/api/v1/knowledge", headers=headers)).json() == []
    assert (await client.get(f"/api/v1/jobs/{job.id}", headers=headers)).json()[
        "status"
    ] == "CANCELLED"


async def test_200_files_10mb_and_ten_citation_samples(
    client: AsyncClient, pg: TestDatabase
) -> None:
    headers, source = await connect(client)
    files: dict[str, bytes] = {}
    for number in range(200):
        prefix = f"# Topic{number}\n\nA learning note with a source.\n\n".encode()
        files[f"note{number}.md"] = prefix + b"x" * (50_000 - len(prefix))
    fixture = GitHubFixture(files)
    assert sum(len(content) for content in files.values()) == 10_000_000
    result = await synchronize(client, pg, headers, source.id, fixture)
    assert result.status == "SUCCEEDED"
    async with pg.factory() as db:
        assert await db.scalar(select(func.count()).select_from(SourceDocument)) == 200
    states = (await client.get("/api/v1/knowledge?limit=500", headers=headers)).json()
    assert len(states) >= 200
    for state in states[:10]:
        assert state["level"] == "EXPOSED"
        evidence = (
            await client.get(f"/api/v1/knowledge/{state['concept_id']}/evidence", headers=headers)
        ).json()
        assert evidence
        for item in evidence:
            locator = item["source_locator"]
            assert item["excerpt"] in files[locator["path"]].decode()
            assert locator["commit_sha"] == fixture.revision
