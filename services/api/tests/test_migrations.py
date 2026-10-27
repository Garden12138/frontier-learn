import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

API_ROOT = Path(__file__).resolve().parents[1]
HEAD = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini"))).get_current_head()


@pytest.mark.postgres
async def test_migration_upgrade_rollback_and_metadata_match() -> None:
    """Only run against a dedicated, explicitly supplied disposable test database."""
    url = os.environ.get("FRONTIER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set FRONTIER_TEST_DATABASE_URL to an isolated PostgreSQL database")
    env = {**os.environ, "FRONTIER_DATABASE_URL": url, "FRONTIER_ENV": "test"}

    def alembic(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Do not echo stderr: a driver exception could contain connection details.
        assert result.returncode == 0, f"Alembic {args[0]} failed"

    engine = create_async_engine(url)
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
    assert set(tables) <= {"alembic_version"}, "Refusing to reset a nonempty test database"
    try:
        await asyncio.to_thread(alembic, "upgrade", "head")
        async with engine.connect() as connection:
            version = await connection.execute(text("SELECT version_num FROM alembic_version"))
            assert version.scalar() == HEAD
            tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
            assert "users" in tables
        await asyncio.to_thread(alembic, "check")
        await asyncio.to_thread(alembic, "downgrade", "base")
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
            assert "users" not in tables
        await asyncio.to_thread(alembic, "upgrade", "head")
    finally:
        await asyncio.to_thread(alembic, "downgrade", "base")
        await engine.dispose()
