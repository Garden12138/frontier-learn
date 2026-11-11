"""Opt-in, GET-only connection observer; a passing test can record a failed sync.

Not collected by offline pytest. Uses the guarded disposable database fixture and
the real SSRF-protected reader. Never accepts credentials or calls a model.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from httpx import AsyncClient
from pydantic import SecretStr

from app.connectors.github import GitHubConnector
from app.core.config import Settings
from app.domain.knowledge_sync import sync_handler
from app.ingestion.http_reader import PinnedHTTPReader, ReadResponse
from app.jobs.service import run_one
from tests.conftest import TestDatabase
from tests.planning_fixture import authenticate

PREFIX = "ai/skills/agent-persona-creator/references/"
SAFE_HEADERS = frozenset(
    {
        "date",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-used",
        "x-ratelimit-reset",
        "x-ratelimit-resource",
        "retry-after",
    }
)


class ObservedReader:
    def __init__(self) -> None:
        self.reader = PinnedHTTPReader(frozenset({"api.github.com"}))
        self.requests: list[dict[str, object]] = []

    async def get(self, url: str, *, headers: dict[str, str], max_bytes: int) -> ReadResponse:
        assert len(self.requests) < 8, "Small-directory diagnostic request budget exhausted"
        assert "Authorization" not in headers, "Observer only supports public unauthenticated GET"
        record: dict[str, object] = {"method": "GET", "url": url, "authenticated": False}
        self.requests.append(record)
        try:
            response = await self.reader.get(url, headers=headers, max_bytes=max_bytes)
        except Exception:
            record["transport_error"] = "NO_HTTP_RESPONSE"
            raise
        record.update(
            {
                "http_status": response.status,
                "headers": {k: v for k, v in response.headers.items() if k in SAFE_HEADERS},
                "response_bytes": len(response.body),
            }
        )
        return response


async def test_record_small_directory_connection(client: AsyncClient, pg: TestDatabase) -> None:
    assert os.environ.get("FRONTIER_LIVE_CONNECTION_CHECK") == "true", "Explicit opt-in required"
    headers = await authenticate(client, "isolated-public-connection-observer")
    source = await client.post(
        "/api/v1/sources",
        headers=headers,
        json={"external_ref": "Garden12138/notes", "consent": True, "path_prefixes": [PREFIX]},
    )
    assert source.status_code == 201
    source_id = source.json()["id"]
    reader = ObservedReader()

    def connector(repository: str, token: SecretStr | None) -> GitHubConnector:
        assert token is None
        return GitHubConnector(repository, reader=reader)

    async def synchronize() -> dict[str, object]:
        reply = await client.post(
            f"/api/v1/sources/{source_id}/sync",
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        assert reply.status_code == 202
        assert await run_one(
            pg.factory, {"GITHUB_SYNC": sync_handler(pg.factory, Settings(), connector)}
        )
        job: dict[str, object] = (
            await client.get(f"/api/v1/jobs/{reply.json()['id']}", headers=headers)
        ).json()
        return {k: job[k] for k in ("id", "status", "error_code", "attempt_count", "max_attempts")}

    job = await synchronize()
    documents = (await client.get(f"/api/v1/sources/{source_id}/documents", headers=headers)).json()
    report: dict[str, object] = {
        "observed_at": datetime.now(UTC).isoformat(),
        "mode": "REAL_CONNECTOR_AND_JOB_HANDLER_ISOLATED_DATABASE_NO_MODEL",
        "repository": "Garden12138/notes",
        "path_prefix": PREFIX,
        "job": job,
        "document_count": len(documents),
        "live_sync_passed": job["status"] == "SUCCEEDED",
        "repeat_sync": "NOT_RUN_AFTER_FAILURE",
        "automatic_retries": 0,
        "human_learning_samples": 0,
    }
    if job["status"] == "SUCCEEDED":
        assert 0 < len(documents) <= 2
        second = await synchronize()
        repeated = (
            await client.get(f"/api/v1/sources/{source_id}/documents", headers=headers)
        ).json()
        assert second["status"] == "SUCCEEDED" and repeated == documents
        report["repeat_sync"] = second
    else:
        assert job["status"] in {"FAILED", "PARTIAL"} and job["error_code"]
    report["http_request_count"] = len(reader.requests)
    report["requests"] = reader.requests
    output = Path(__file__).parents[4] / "test-results/v0.1.1"
    output.mkdir(parents=True, exist_ok=True)
    (output / "connection-diagnostic.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
