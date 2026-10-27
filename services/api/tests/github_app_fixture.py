import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import SecretStr

from app.core.config import Settings
from app.ingestion.http_reader import ReadResponse


def app_settings(
    database_url: str, web: str = "http://localhost:5173", api: str = "http://localhost:8000"
) -> Settings:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return Settings(
        env="test",
        database_url=SecretStr(database_url),
        mock_auth=True,
        writeback_enabled=True,
        encryption_key=SecretStr(Fernet.generate_key().decode()),
        github_app_id="123",
        github_client_id="fixtureclient",
        github_client_secret=SecretStr("fixture-oauth-client-secret"),
        github_private_key=SecretStr(pem),
        github_app_slug="frontier-fixture",
        public_web_url=web,
        public_api_url=api,
        allowed_origins=[web],
    )


class AppFixture:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scope_requests: list[dict[str, object]] = []
        self.events: list[str] = []
        self.pause_exchange = False
        self.exchange_started = asyncio.Event()
        self.exchange_release = asyncio.Event()
        self.push = True
        self.installed = True
        self.user_allowed = True
        self.expected_challenge: str | None = None
        self.fail_repo = False

    def check_jwt(self, value: str) -> None:
        header, body, signature = value.split(".")
        raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        assert self.settings.github_private_key
        key = serialization.load_pem_private_key(
            self.settings.github_private_key.get_secret_value().encode(), password=None
        )
        assert isinstance(key, rsa.RSAPrivateKey)
        key.public_key().verify(
            raw, (header + "." + body).encode(), padding.PKCS1v15(), hashes.SHA256()
        )
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        assert claims["iss"] == self.settings.github_client_id
        assert 0 < claims["exp"] - int(datetime.now(UTC).timestamp()) <= 600

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        max_bytes: int,
        content: bytes = b"",
    ) -> ReadResponse:
        parsed = urlsplit(url)
        self.events.append(parsed.path)
        data = json.loads(content) if content else {}
        result: dict[str, object]
        status = 200
        if parsed.hostname == "github.com":
            assert data["client_secret"] == "fixture-oauth-client-secret"
            if self.pause_exchange and data.get("grant_type") != "refresh_token":
                self.exchange_started.set()
                await self.exchange_release.wait()
            if data.get("grant_type") == "refresh_token":
                assert data["refresh_token"] == "ghr_fixture_old"
                result = {
                    "access_token": "ghu_fixture_new",
                    "refresh_token": "ghr_fixture_new",
                    "expires_in": 28800,
                }
            else:
                if self.expected_challenge:
                    actual = (
                        base64.urlsafe_b64encode(
                            hashlib.sha256(data["code_verifier"].encode()).digest()
                        )
                        .decode()
                        .rstrip("=")
                    )
                    assert actual == self.expected_challenge
                result = {
                    "access_token": "ghu_fixture_old",
                    "refresh_token": "ghr_fixture_old",
                    "expires_in": 28800,
                }
        elif parsed.path == "/user":
            result = {"id": 789, "login": "fixture-learner"}
        elif parsed.path == "/user/installations":
            result = {"installations": [{"id": 7, "app_id": 123, "account": {"login": "sample"}}]}
        elif parsed.path == "/user/installations/7/repositories":
            result = {
                "repositories": [{"id": 101, "full_name": "sample/private-notes", "private": True}]
            }
        elif parsed.path == "/repos/sample/private-notes":
            status = 500 if self.fail_repo else 200 if self.user_allowed else 403
            result = {"id": 101, "permissions": {"pull": True, "push": self.push}}
        elif parsed.path == "/repos/sample/private-notes/installation":
            self.check_jwt(headers["Authorization"].removeprefix("Bearer "))
            status = 200 if self.installed else 404
            result = {"id": 7, "app_id": 123}
        elif parsed.path == "/app/installations/7/access_tokens":
            self.check_jwt(headers["Authorization"].removeprefix("Bearer "))
            assert data["repository_ids"] == [101]
            self.scope_requests.append(data)
            result = {
                "token": "ghs_fixture_" + data["permissions"]["contents"],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        else:
            status, result = 404, {}
        return ReadResponse(status, {}, json.dumps(result).encode())
