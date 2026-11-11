"""Restore verification must accept current migrations and reject changed learning data."""

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from tests.acceptance.backup_restore import seed, verify
from tests.conftest import TestDatabase


async def test_restore_verifier_accepts_current_schema_and_checks_export(pg: TestDatabase) -> None:
    key = SecretStr(Fernet.generate_key().decode())
    password = "synthetic restore regression password"
    credential = SecretStr("synthetic-restore-connection")
    headers, exported, goal_id = await seed(pg.url, key, password, credential)

    assert await verify(pg.url, key, password, credential, headers, exported, goal_id) == len(
        exported.encode()
    )
    with pytest.raises(AssertionError):
        await verify(pg.url, key, password, credential, headers, "{}", goal_id)
