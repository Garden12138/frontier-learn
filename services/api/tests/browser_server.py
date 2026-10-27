"""Isolated browser acceptance server. Never imported by the production app or worker."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.ai.openai_provider import OpenAIProvider
from app.connectors.github import GitHubConnector
from app.connectors.github_app import GitHubAppClient
from app.domain.conversation_learning import conversation_handler
from app.domain.knowledge_sync import sync_handler
from app.domain.tutor import tutor_handler
from app.domain.writeback import writeback_handler
from app.ingestion.safe_fetch import ShareFetcher
from app.jobs.service import run_one
from app.main import create_app
from tests.conversation_fixture import ShareFixtureReader
from tests.github_app_fixture import AppFixture, app_settings
from tests.github_fixture import GitHubFixture
from tests.test_openai_provider import ResponsesFixture
from tests.writeback_fixture import WriteFixture

API_ROOT = Path(__file__).resolve().parents[1]
url = os.environ.get("FRONTIER_TEST_DATABASE_URL", "")
if not url or not (make_url(url).database or "").startswith("frontier_test"):
    raise RuntimeError("Browser acceptance requires an explicitly isolated test database")
settings = app_settings(url, web="http://127.0.0.1:5175", api="http://127.0.0.1:18002")
settings = settings.model_copy(
    update={
        "llm_provider": "openai_responses",
        "openai_model": "configured-test-model",
        "openai_api_key": SecretStr("fixture-model-secret"),
    }
)
app_remote = AppFixture(settings)
model_remote = ResponsesFixture()
app = create_app(settings)
write_remote = WriteFixture()
app.state.write_transport = write_remote
app.state.github_app_transport = app_remote
original_lifespan = app.router.lifespan_context
samples = {
    "BPE.md": b"# BPE\n\nByte pair encoding merges frequent token pairs.",
    "Attention.md": b"# Attention\n\nGQA appears in this note without a quiz.",
    "Agent.md": b"# Agent Memory\n\nRetrieval supports memory.",
    "Garden.md": (
        "# 园艺基础\n\n土壤与浇水是学习线索。\n\n## 土壤湿度\n\n应结合植物种类观察。"
    ).encode(),
}


def connector(repository: str, token: SecretStr | None) -> GitHubConnector:
    reader = GitHubFixture(samples)
    if repository == "sample/denied":
        reader.status = 403
    if repository == "sample/partial":
        reader.files = {**samples, "broken.md": b"\xff\xfe"}
    return GitHubConnector(repository, token, reader)


def migrate(direction: str, target: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", direction, target],
        cwd=API_ROOT,
        env={**os.environ, "FRONTIER_DATABASE_URL": url, "FRONTIER_ENV": "test"},
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("Browser database migration failed")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    guard_engine = create_async_engine(url)
    async with guard_engine.connect() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
    await guard_engine.dispose()
    if set(tables) - {"alembic_version"}:
        raise RuntimeError("Refusing to clear a nonempty test database")
    await asyncio.to_thread(migrate, "upgrade", "head")
    try:
        async with original_lifespan(application):
            stop = asyncio.Event()

            async def worker() -> None:
                handlers = {
                    "GITHUB_SYNC": sync_handler(
                        application.state.sessions,
                        settings,
                        connector,
                        lambda: GitHubAppClient(settings, app_remote),
                    ),
                    "TUTOR_GUIDE": tutor_handler(
                        application.state.sessions,
                        OpenAIProvider(
                            SecretStr("fixture-model-secret"), "configured-test-model", model_remote
                        ),
                        settings=settings,
                        fallback_without_consent=True,
                    ),
                    "GITHUB_WRITEBACK": writeback_handler(
                        application.state.sessions, settings, lambda: write_remote
                    ),
                    "CONVERSATION_IMPORT": conversation_handler(
                        application.state.sessions, ShareFetcher(ShareFixtureReader())
                    ),
                }
                while not stop.is_set():
                    await run_one(application.state.sessions, handlers)
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.1)
                    except TimeoutError:
                        pass

            task = asyncio.create_task(worker())
            try:
                yield
            finally:
                stop.set()
                await task
    finally:
        await asyncio.to_thread(migrate, "downgrade", "base")


app.router.lifespan_context = lifespan
