"""Restore synthetic data into a NEW disposable database; never overwrite a database.

Run from services/api with the exact local Compose test database URL configured.
Docker's PostgreSQL 16 client performs a real custom-format dump and restore.
No external service or paid model is called. Credentials/dump contents are never printed.
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.core.security import TokenVault
from app.main import create_app
from app.persistence.database import create_session_factory
from app.persistence.models import GitHubConnection, User
from tests.conftest import API_ROOT, TestDatabase
from tests.integration.test_learning_loop import assessed
from tests.planning_fixture import generate, make_goal

ROOT = API_ROOT.parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "infra/compose.test.yml")]


def command(args: list[str], *, content: bytes | None = None) -> bytes:
    result = subprocess.run(args, input=content, capture_output=True, timeout=30, cwd=API_ROOT)
    if result.returncode:
        # Driver output may contain credentials or data: do not print it.
        raise RuntimeError("Backup/restore subprocess failed; no sensitive output was recorded")
    return result.stdout


def pg_command(*args: str, content: bytes | None = None) -> bytes:
    return command([*COMPOSE, "exec", "-T", "db", *args], content=content)


def migrate(url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env={**os.environ, "FRONTIER_ENV": "test", "FRONTIER_DATABASE_URL": url},
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError("Isolated migration failed")


def settings(url: str, key: SecretStr) -> Settings:
    return Settings(
        env="test",
        database_url=SecretStr(url),
        encryption_key=key,
        mock_auth=False,
        password_auth=True,
        llm_provider="local_rules",
        openai_api_key=None,
        writeback_enabled=False,
        github_app_id="",
        github_client_id="",
        github_client_secret=None,
        github_private_key=None,
        github_app_slug="",
    )


def stable_export(value: dict[str, object]) -> str:
    return json.dumps(
        {key: item for key, item in value.items() if key != "exported_at"},
        sort_keys=True,
        ensure_ascii=False,
    )


async def seed(
    url: str, key: SecretStr, password: str, connection_secret: SecretStr
) -> tuple[dict[str, str], str, str]:
    config = settings(url, key)
    app = create_app(config)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            registered = await client.post(
                "/api/v1/auth/register",
                json={"identity": "restore-learner", "password": password, "client": "extension"},
            )
            assert registered.status_code == 201
            headers = {"Authorization": "Bearer " + registered.json()["access_token"]}
            goal = await make_goal(client, headers, title="Attention")
            await generate(client, headers, goal)
            assessment = await assessed(
                client, TestDatabase(url, app.state.sessions), headers, goal.id
            )
            confirmed = await client.post(
                f"/api/v1/assessments/{assessment['id']}/confirm",
                headers=headers,
                json={"version": 2, "confirm": True},
            )
            assert confirmed.status_code == 200
            draft = await client.post(
                "/api/v1/artifacts", headers=headers, json={"assessment_id": assessment["id"]}
            )
            assert draft.status_code == 201
            async with app.state.sessions.begin() as db:
                user = await db.scalar(select(User))
                assert user
                db.add(
                    GitHubConnection(
                        user_id=user.id,
                        github_user_id=123,
                        login="synthetic-restore-account",
                        encrypted_token=TokenVault(key).encrypt(connection_secret),
                        status="CONNECTED",
                    )
                )
            exported = await client.get("/api/v1/settings/export", headers=headers)
            assert exported.status_code == 200
            document = cast(dict[str, object], exported.json())
            assert document["learning_artifacts"] and document["assessments"]
            return headers, stable_export(document), str(goal.id)


async def verify(
    url: str,
    key: SecretStr,
    password: str,
    connection_secret: SecretStr,
    headers: dict[str, str],
    before: str,
    goal_id: str,
) -> int:
    app = create_app(settings(url, key))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            exported = await client.get("/api/v1/settings/export", headers=headers)
            assert exported.status_code == 200
            assert stable_export(cast(dict[str, object], exported.json())) == before
            login = await client.post(
                "/api/v1/auth/login",
                json={"identity": "restore-learner", "password": password, "client": "extension"},
            )
            assert login.status_code == 200
            authenticated = {"Authorization": "Bearer " + login.json()["access_token"]}
            goals = await client.get("/api/v1/goals", headers=authenticated)
            assert goals.status_code == 200 and goals.json()[0]["id"] == goal_id
            async with app.state.sessions() as db:
                assert await db.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0009_real_connections"
                )
                connection = await db.scalar(select(GitHubConnection))
                assert connection and connection.encrypted_token
                assert TokenVault(key).decrypt(connection.encrypted_token) == connection_secret
                user_id = UUID(str(exported.json()["user"]["id"]))
                assert await db.get(User, user_id)
            return len(before.encode())


async def run() -> dict[str, object]:
    supplied = os.environ.get("FRONTIER_TEST_DATABASE_URL", "")
    parsed = make_url(supplied)
    if (
        parsed.drivername != "postgresql+asyncpg"
        or parsed.host != "127.0.0.1"
        or parsed.port != 55432
        or parsed.username != "frontier"
        or parsed.database != "frontier_test"
    ):
        raise RuntimeError("Requires the explicit local Compose test database")
    port = (await asyncio.to_thread(command, [*COMPOSE, "port", "db", "5432"])).decode().strip()
    if port != "127.0.0.1:55432":
        raise RuntimeError("Test container port does not match the isolated database URL")
    suffix = uuid4().hex[:12]
    names = ["frontier_test_backup_" + suffix, "frontier_test_restore_" + suffix]
    urls = [parsed.set(database=name).render_as_string(hide_password=False) for name in names]
    key = SecretStr(Fernet.generate_key().decode())
    password, connection_secret = secrets.token_urlsafe(32), SecretStr(secrets.token_urlsafe(32))
    created: list[str] = []
    try:
        for name in names:
            await asyncio.to_thread(pg_command, "createdb", "-U", "frontier", name)
            created.append(name)
        await asyncio.to_thread(migrate, urls[0])
        headers, before, goal_id = await seed(urls[0], key, password, connection_secret)
        started = time.perf_counter()
        data = await asyncio.to_thread(
            pg_command, "pg_dump", "-U", "frontier", "-Fc", "--no-owner", names[0]
        )
        if not data or len(data) > 20_000_000:
            raise RuntimeError("Synthetic dump exceeds the rehearsal limit")
        with tempfile.TemporaryDirectory(prefix="frontier-restore-") as folder:
            dump = Path(folder) / "synthetic.dump"
            descriptor = os.open(dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
            await asyncio.to_thread(
                pg_command,
                "pg_restore",
                "-U",
                "frontier",
                "--exit-on-error",
                "--no-owner",
                "--dbname",
                names[1],
                content=dump.read_bytes(),
            )
        restored_bytes = await verify(
            urls[1], key, password, connection_secret, headers, before, goal_id
        )
        engine = create_async_engine(urls[1])
        try:
            async with create_session_factory(engine)() as db:
                tables = await db.scalar(
                    text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
                )
        finally:
            await engine.dispose()
        return {
            "observed_at": datetime.now(UTC).isoformat(),
            "result": "PASSED",
            "schema_head": "0009_real_connections",
            "restored_tables": tables,
            "dump_bytes": len(data),
            "dump_sha256": hashlib.sha256(data).hexdigest(),
            "export_bytes_compared": restored_bytes,
            "dump_restore_verify_seconds": round(time.perf_counter() - started, 3),
            "learning_export_equal": True,
            "original_password_login": True,
            "encrypted_connection_recovered_with_original_key": True,
            "cloud_requests": 0,
            "external_writes": 0,
            "scope": "SYNTHETIC_LOCAL_NEW_DATABASES_ONLY_NOT_PRODUCTION_DRILL",
        }
    finally:
        for name in reversed(created):
            await asyncio.to_thread(pg_command, "dropdb", "-U", "frontier", "--force", name)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
    except Exception:
        # No raw driver errors, database URLs, tokens, passwords or dump contents.
        print('{"result":"FAILED","reason":"ISOLATED_RESTORE_CHECK_FAILED"}')
        raise SystemExit(1) from None
