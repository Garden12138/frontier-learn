import asyncio
import base64
import hashlib
import hmac
import secrets
import unicodedata
from datetime import UTC, datetime
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Problem
from app.core.security import digest_token
from app.persistence.models import AuthRateLimit

N, R, P = 2**17, 8, 1


class PasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    identity: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=12, max_length=128)
    client: Literal["web", "extension"] = "web"

    @field_validator("identity")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        value = unicodedata.normalize("NFKC", value).strip().casefold()
        if not 3 <= len(value) <= 64 or not all(c.isalnum() or c in "._-" for c in value):
            raise ValueError("Choose a username with letters, numbers, dots, underscores or dashes")
        return value


class RecoveryRequest(PasswordRequest):
    recovery_code: SecretStr = Field(min_length=32, max_length=100)


async def rate_limit(db: AsyncSession, request: Request, identity: str) -> None:
    window = int(datetime.now(UTC).timestamp()) // 900
    key = request.app.state.settings.encryption_key
    pepper = key.get_secret_value().encode() if key else b"frontier-development-only-rate-limit"
    ip = request.client.host if request.client else "unknown"
    for label, limit in [("global", 1000), ("ip:" + ip, 60), ("identity:" + identity, 20)]:
        digest = hmac.new(pepper, label.encode(), hashlib.sha256).hexdigest()
        statement = insert(AuthRateLimit).values(key=digest, window=window, attempts=1)
        attempts = await db.scalar(
            statement.on_conflict_do_update(
                index_elements=[AuthRateLimit.key, AuthRateLimit.window],
                set_={"attempts": AuthRateLimit.attempts + 1},
            ).returning(AuthRateLimit.attempts)
        )
        if attempts and attempts > limit:
            await db.commit()
            raise Problem(429, "AUTH_RATE_LIMIT", "尝试次数过多，请在 15 分钟后重试。")
    await db.execute(delete(AuthRateLimit).where(AuthRateLimit.window < window - 96))
    # Failure must still consume the rate allowance after the route raises an error.
    await db.commit()


async def derive(password: SecretStr, salt: bytes, slots: asyncio.Semaphore) -> bytes:
    try:
        async with asyncio.timeout(0.25):
            await slots.acquire()
    except TimeoutError:
        raise Problem(429, "AUTH_BUSY", "登录服务正忙，请稍后重试。") from None
    task = asyncio.create_task(
        asyncio.to_thread(
            hashlib.scrypt,
            password.get_secret_value().encode(),
            salt=salt,
            n=N,
            r=R,
            p=P,
            maxmem=256 * 1024 * 1024,
            dklen=32,
        )
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A disconnected caller cannot release a hashing slot while its thread still runs.
        await task
        raise
    finally:
        slots.release()


async def password_hash(password: SecretStr, slots: asyncio.Semaphore) -> str:
    salt = secrets.token_bytes(16)
    value = await derive(password, salt, slots)
    return (
        f"scrypt${N}${R}${P}$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(value).decode()
    )


async def password_matches(
    password: SecretStr, encoded: str | None, slots: asyncio.Semaphore
) -> bool:
    salt, expected, valid = b"0" * 16, b"0" * 32, encoded is not None
    if encoded:
        try:
            algorithm, n, r, p, salt_text, digest = encoded.split("$")
            salt, expected = (
                base64.b64decode(salt_text, validate=True),
                base64.b64decode(digest, validate=True),
            )
            if (
                (algorithm, int(n), int(r), int(p)) != ("scrypt", N, R, P)
                or len(salt) != 16
                or len(expected) != 32
            ):
                raise ValueError
        except (ValueError, TypeError):
            valid, salt, expected = False, b"0" * 16, b"0" * 32
    actual = await derive(password, salt, slots)
    return hmac.compare_digest(actual, expected) and valid


def recovery_matches(code: SecretStr, stored: str | None) -> bool:
    return hmac.compare_digest(digest_token(code.get_secret_value()), stored or "0" * 64)
