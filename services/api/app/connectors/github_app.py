import base64
import json
import time
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned
from app.connectors.github import repository_ref
from app.connectors.github_writeback import WriteTransport
from app.core.config import Settings
from app.core.errors import Problem
from app.core.security import TokenVault
from app.ingestion.http_reader import PinnedHTTPReader
from app.persistence.models import GitHubConnection, KnowledgeSource


def configured(settings: Settings) -> bool:
    return bool(
        settings.github_app_id
        and settings.github_client_id
        and settings.github_client_secret
        and settings.github_private_key
        and settings.github_app_slug
    )


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class GitHubAppClient:
    def __init__(self, settings: Settings, transport: WriteTransport | None = None) -> None:
        if not configured(settings):
            raise Problem(
                503, "GITHUB_APP_DISABLED", "GitHub App 尚未配置；仍可连接公开仓库或本地保存。"
            )
        self.settings = settings
        self.transport = transport or PinnedHTTPReader(frozenset({"api.github.com", "github.com"}))
        self.requests = 0

    def jwt(self) -> SecretStr:
        assert self.settings.github_private_key is not None
        try:
            key = serialization.load_pem_private_key(
                self.settings.github_private_key.get_secret_value().encode(), password=None
            )
            if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
                raise ValueError
            now = int(time.time())
            data = (
                b64(b'{"alg":"RS256","typ":"JWT"}')
                + "."
                + b64(
                    json.dumps(
                        {"iat": now - 60, "exp": now + 540, "iss": self.settings.github_client_id}
                    ).encode()
                )
            )
            signature = key.sign(data.encode(), padding.PKCS1v15(), hashes.SHA256())
            return SecretStr(data + "." + b64(signature))
        except (ValueError, TypeError):
            raise Problem(
                503, "GITHUB_APP_KEY", "GitHub App 私钥配置不可用，请联系管理员。"
            ) from None

    async def call(
        self,
        method: str,
        path: str,
        token: SecretStr | None = None,
        data: dict[str, object] | None = None,
        *,
        oauth: bool = False,
    ) -> dict[str, object]:
        self.requests += 1
        if self.requests > 24 or method not in {"GET", "POST"}:
            raise Problem(413, "GITHUB_APP_LIMIT", "本次授权操作已达到请求上限。")
        headers = {
            "Accept": "application/json" if oauth else "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = "Bearer " + token.get_secret_value()
        url = (
            "https://github.com/login/oauth/access_token"
            if oauth
            else "https://api.github.com" + path
        )
        response = await self.transport.request(
            method,
            url,
            headers=headers,
            max_bytes=300000,
            content=json.dumps(data).encode() if data else b"",
        )
        if response.status in {401, 403, 404}:
            raise Problem(
                403, "GITHUB_REAUTHORIZE", "GitHub 授权已失效或无权限，请重新连接或选择已授权仓库。"
            )
        if response.status not in {200, 201}:
            raise Problem(503, "GITHUB_APP_UNAVAILABLE", "GitHub 暂不可用，请稍后重试。")
        try:
            result = json.loads(response.body)
            if not isinstance(result, dict) or "error" in result:
                raise ValueError
            return result
        except (ValueError, UnicodeError):
            raise Problem(403, "GITHUB_AUTH_FAILED", "GitHub 未能完成授权，请重新连接。") from None

    async def exchange(self, fields: dict[str, object]) -> dict[str, object]:
        assert self.settings.github_client_secret is not None
        return await self.call(
            "POST",
            "",
            data={
                **fields,
                "client_id": self.settings.github_client_id,
                "client_secret": self.settings.github_client_secret.get_secret_value(),
            },
            oauth=True,
        )

    def credentials(self, row: GitHubConnection, result: dict[str, object]) -> None:
        token, refresh, expires = (
            result.get("access_token"),
            result.get("refresh_token"),
            result.get("expires_in"),
        )
        if not isinstance(token, str) or not 1 <= len(token) <= 8000:
            raise Problem(502, "GITHUB_AUTH_RESPONSE", "GitHub 授权响应不完整。")
        vault = TokenVault(self.settings.encryption_key)
        row.encrypted_token = vault.encrypt(SecretStr(token))
        row.encrypted_refresh = (
            vault.encrypt(SecretStr(refresh)) if isinstance(refresh, str) and refresh else None
        )
        if expires is not None and (not isinstance(expires, int) or not 1 <= expires <= 28800):
            raise Problem(502, "GITHUB_AUTH_RESPONSE", "GitHub 令牌有效期无效。")
        row.expires_at = (
            datetime.now(UTC) + timedelta(seconds=expires) if isinstance(expires, int) else None
        )
        row.status = "CONNECTED"

    async def user_token(self, db: AsyncSession, connection: GitHubConnection) -> SecretStr:
        if connection.status != "CONNECTED" or not connection.encrypted_token:
            raise Problem(403, "GITHUB_REAUTHORIZE", "GitHub 连接已撤销，请重新授权。")
        if connection.expires_at is None or connection.expires_at > datetime.now(UTC) + timedelta(
            seconds=60
        ):
            return TokenVault(self.settings.encryption_key).decrypt(connection.encrypted_token)
        # Commit a rotated refresh token independently of a later preview/permission failure.
        async with AsyncSession(bind=db.bind, expire_on_commit=False) as token_db:
            async with token_db.begin():
                row = await get_owned(token_db, GitHubConnection, connection.user_id, connection.id)
                await token_db.refresh(row, with_for_update=True)
                if row.status != "CONNECTED" or not row.encrypted_token:
                    raise Problem(403, "GITHUB_REAUTHORIZE", "GitHub 连接已撤销，请重新授权。")
                vault = TokenVault(self.settings.encryption_key)
                if row.expires_at and row.expires_at <= datetime.now(UTC) + timedelta(seconds=60):
                    if not row.encrypted_refresh:
                        raise Problem(403, "GITHUB_REAUTHORIZE", "GitHub 连接已过期，请重新授权。")
                    result = await self.exchange(
                        {
                            "grant_type": "refresh_token",
                            "refresh_token": vault.decrypt(
                                row.encrypted_refresh
                            ).get_secret_value(),
                        }
                    )
                    self.credentials(row, result)
                return vault.decrypt(row.encrypted_token)

    async def source_token(
        self, db: AsyncSession, source: KnowledgeSource, *, write: bool = False
    ) -> SecretStr:
        if (
            source.github_connection_id is None
            or not source.github_repository_id
            or not source.github_installation_id
        ):
            raise Problem(403, "GITHUB_REAUTHORIZE", "此来源尚未绑定 GitHub App。")
        row = await get_owned(db, GitHubConnection, source.user_id, source.github_connection_id)
        token = await self.user_token(db, row)
        repository = repository_ref(source.external_ref)
        repo = await self.call("GET", "/repos/" + repository, token)
        if repo.get("id") != source.github_repository_id:
            raise Problem(403, "GITHUB_REPOSITORY_CHANGED", "仓库身份已变化，请重新选择仓库。")
        permissions = repo.get("permissions")
        if not isinstance(permissions, dict) or permissions.get("pull") is not True:
            raise Problem(403, "GITHUB_REAUTHORIZE", "当前 GitHub 用户没有此仓库读取权限。")
        if write and (not isinstance(permissions, dict) or permissions.get("push") is not True):
            raise Problem(403, "WRITE_PERMISSION", "当前 GitHub 用户没有该仓库写权限。")
        installation = await self.call("GET", "/repos/" + repository + "/installation", self.jwt())
        if (
            installation.get("id") != source.github_installation_id
            or str(installation.get("app_id")) != self.settings.github_app_id
        ):
            raise Problem(403, "GITHUB_INSTALLATION_CHANGED", "App 安装范围已变化，请重新连接。")
        scope = {"contents": "write" if write else "read", "metadata": "read"}
        if write:
            scope["pull_requests"] = "write"
        access = await self.call(
            "POST",
            f"/app/installations/{source.github_installation_id}/access_tokens",
            self.jwt(),
            {"repository_ids": [source.github_repository_id], "permissions": scope},
        )
        value, expiry = access.get("token"), access.get("expires_at")
        try:
            expiration = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            if expiration.tzinfo is None or not datetime.now(UTC) < expiration <= datetime.now(
                UTC
            ) + timedelta(hours=2):
                raise ValueError
        except ValueError:
            raise Problem(502, "GITHUB_AUTH_RESPONSE", "GitHub 临时令牌有效期无效。") from None
        if not isinstance(value, str) or not 1 <= len(value) <= 8000:
            raise Problem(502, "GITHUB_AUTH_RESPONSE", "GitHub 临时令牌响应无效。")
        return SecretStr(value)
