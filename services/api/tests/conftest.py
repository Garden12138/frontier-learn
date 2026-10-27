import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class TestDatabase:
    __test__ = False
    url: str
    factory: async_sessionmaker[AsyncSession]


@pytest.fixture
async def pg() -> AsyncIterator[TestDatabase]:
    url = os.environ.get("FRONTIER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires isolated FRONTIER_TEST_DATABASE_URL")
    database = make_url(url).database or ""
    assert database.startswith("frontier_test"), "Refusing to migrate a non-test database"
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
    assert set(tables) <= {"alembic_version"}, "Refusing to clear existing business tables"
    env = {**os.environ, "FRONTIER_DATABASE_URL": url, "FRONTIER_ENV": "test"}

    def migrate(direction: str, target: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", direction, target],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Test migration {direction} failed"

    await asyncio.to_thread(migrate, "upgrade", "head")
    try:
        yield TestDatabase(url, async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()
        await asyncio.to_thread(migrate, "downgrade", "base")


@pytest.fixture
async def client(pg: TestDatabase) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(env="test", database_url=SecretStr(pg.url), mock_auth=True))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as connection:
            yield connection
