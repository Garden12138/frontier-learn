import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.api.sources import SourceResponse
from app.auth.dependencies import CurrentUser, Db, get_owned
from app.connectors.github import normalize_prefixes, repository_ref
from app.connectors.github_app import GitHubAppClient, b64, configured
from app.core.errors import Problem
from app.core.security import TokenVault, digest_token
from app.persistence.models import (
    AuditEvent,
    AuthSession,
    GitHubConnection,
    GitHubOAuthState,
    Job,
    KnowledgeSource,
    User,
)

router = APIRouter(prefix="/github", tags=["GitHub App"])
COOKIE = "frontier_github_browser"


class GitHubStatus(BaseModel):
    available: bool
    connected: bool
    login: str | None = None
    install_url: str | None = None


class AuthorizationResponse(BaseModel):
    authorization_url: str


class RepositoryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    repository: str = Field(min_length=3, max_length=256)
    path_prefixes: list[str] = Field(default_factory=list, max_length=5)
    confirm: Literal[True]

    @field_validator("path_prefixes")
    @classmethod
    def paths(cls, value: list[str]) -> list[str]:
        return normalize_prefixes(value)


class GitHubWritePermission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    path_prefixes: list[str] = Field(min_length=1, max_length=5)
    confirm: Literal[True]

    @field_validator("path_prefixes")
    @classmethod
    def paths(cls, value: list[str]) -> list[str]:
        return normalize_prefixes(value)


class GitHubInstallation(BaseModel):
    id: int
    account: str


class GitHubRepository(BaseModel):
    id: int
    full_name: str
    private: bool


class InstallationList(BaseModel):
    items: list[GitHubInstallation]
    has_more: bool
    page: int


class RepositoryList(BaseModel):
    items: list[GitHubRepository]
    has_more: bool
    page: int


def client(request: Request) -> GitHubAppClient:
    return GitHubAppClient(
        request.app.state.settings, getattr(request.app.state, "github_app_transport", None)
    )


@router.get("/status", response_model=GitHubStatus)
async def status(user: CurrentUser, db: Db, request: Request) -> GitHubStatus:
    connection = await db.scalar(
        select(GitHubConnection).where(GitHubConnection.user_id == user.id)
    )
    available = configured(request.app.state.settings)
    return GitHubStatus(
        available=available,
        connected=bool(connection and connection.status == "CONNECTED"),
        login=connection.login if connection and connection.status == "CONNECTED" else None,
        install_url="https://github.com/apps/"
        + request.app.state.settings.github_app_slug
        + "/installations/new"
        if available
        else None,
    )


@router.post("/authorize", response_model=AuthorizationResponse)
async def authorize(
    user: CurrentUser, db: Db, request: Request, response: Response
) -> AuthorizationResponse:
    github = client(request)
    await db.refresh(user, with_for_update=True)
    user.github_auth_version += 1
    now = datetime.now(UTC)
    await db.execute(delete(GitHubOAuthState).where(GitHubOAuthState.expires_at <= now))
    await db.execute(delete(GitHubOAuthState).where(GitHubOAuthState.user_id == user.id))
    state, browser, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    db.add(
        GitHubOAuthState(
            user_id=user.id,
            auth_version=user.github_auth_version,
            state_digest=digest_token(state),
            session_digest=request.state.session_digest,
            browser_digest=digest_token(browser),
            encrypted_verifier=TokenVault(github.settings.encryption_key).encrypt(
                SecretStr(verifier)
            ),
            expires_at=now + timedelta(minutes=10),
        )
    )
    await db.commit()
    response.set_cookie(
        COOKIE,
        browser,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=github.settings.public_api_url.startswith("https:"),
        path="/api/v1/github/callback",
    )
    return AuthorizationResponse(
        authorization_url="https://github.com/login/oauth/authorize?"
        + urlencode(
            {
                "client_id": github.settings.github_client_id,
                "state": state,
                "redirect_uri": github.settings.public_api_url.rstrip("/")
                + "/api/v1/github/callback",
                "code_challenge": b64(hashlib.sha256(verifier.encode()).digest()),
                "code_challenge_method": "S256",
            }
        )
    )


@router.get("/callback", response_class=RedirectResponse)
async def callback(
    db: Db,
    request: Request,
    state: Annotated[str, Query(min_length=32, max_length=128)],
    code: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=128)] = None,
) -> RedirectResponse:
    github = client(request)
    row = await db.scalar(
        select(GitHubOAuthState)
        .where(GitHubOAuthState.state_digest == digest_token(state))
        .with_for_update()
    )
    browser = request.cookies.get(COOKIE, "")
    if (
        row is None
        or row.expires_at <= datetime.now(UTC)
        or not browser
        or not hmac.compare_digest(row.browser_digest, digest_token(browser))
    ):
        raise Problem(
            403, "OAUTH_STATE_INVALID", "授权状态已失效或浏览器不匹配，请从工作台重新连接。"
        )
    user_id, session_digest, auth_version = row.user_id, row.session_digest, row.auth_version
    verifier = (
        TokenVault(github.settings.encryption_key)
        .decrypt(row.encrypted_verifier)
        .get_secret_value()
    )
    await db.delete(row)
    await db.commit()
    outcome = "denied"
    if code and not error:
        valid_session = await db.scalar(
            select(AuthSession.id).where(
                AuthSession.user_id == user_id,
                AuthSession.token_digest == session_digest,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
        if valid_session is None:
            raise Problem(401, "OAUTH_SESSION_EXPIRED", "发起授权的登录已失效，请重新登录。")
        result = await github.exchange(
            {
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": github.settings.public_api_url.rstrip("/")
                + "/api/v1/github/callback",
            }
        )
        current_version = await db.scalar(
            select(User.github_auth_version).where(User.id == user_id)
        )
        if current_version != auth_version:
            raise Problem(403, "OAUTH_REVOKED", "授权流程已取消，请重新连接。")
        access = result.get("access_token")
        if not isinstance(access, str):
            raise Problem(403, "GITHUB_AUTH_FAILED", "GitHub 未返回授权凭据。")

        account = await github.call("GET", "/user", SecretStr(access))
        github_id, login = account.get("id"), account.get("login")
        if (
            not isinstance(github_id, int)
            or github_id < 1
            or not isinstance(login, str)
            or len(login) > 100
        ):
            raise Problem(502, "GITHUB_AUTH_RESPONSE", "GitHub 用户信息不完整。")
        owner = await db.scalar(select(User).where(User.id == user_id).with_for_update())
        if owner is None or owner.github_auth_version != auth_version:
            raise Problem(403, "OAUTH_REVOKED", "授权流程已取消，请重新连接。")
        current = await db.scalar(
            select(AuthSession.id).where(
                AuthSession.user_id == user_id,
                AuthSession.token_digest == session_digest,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
        if current is None:
            raise Problem(401, "OAUTH_SESSION_EXPIRED", "登录已撤销，请重新连接。")
        connection = await db.scalar(
            select(GitHubConnection).where(GitHubConnection.user_id == user_id).with_for_update()
        )
        if (
            connection
            and connection.status == "CONNECTED"
            and connection.github_user_id != github_id
        ):
            raise Problem(
                409, "GITHUB_ACCOUNT_CONFLICT", "请先断开原 GitHub 账号，再连接其他账号。"
            )
        if connection is None:
            connection = GitHubConnection(user_id=user_id, github_user_id=github_id, login=login)
            db.add(connection)
        connection.github_user_id, connection.login = github_id, login
        github.credentials(connection, result)
        db.add(
            AuditEvent(
                user_id=user_id,
                operation="GITHUB_CONNECTED",
                object_type="user",
                object_id=str(user_id),
                summary_code="OAUTH_PKCE_BROWSER_BOUND",
            )
        )
        await db.commit()
        outcome = "connected"
    response = RedirectResponse(
        github.settings.public_web_url.rstrip("/") + "/?github=" + outcome, status_code=303
    )
    response.delete_cookie(COOKIE, path="/api/v1/github/callback", httponly=True, samesite="lax")
    return response


@router.get("/installations", response_model=InstallationList)
async def installations(
    user: CurrentUser, db: Db, request: Request, page: Annotated[int, Query(ge=1, le=3)] = 1
) -> dict[str, object]:
    connection = await db.scalar(
        select(GitHubConnection).where(GitHubConnection.user_id == user.id)
    )
    if connection is None:
        raise Problem(403, "GITHUB_REAUTHORIZE", "请先连接 GitHub。")
    github = client(request)
    value = await github.call(
        "GET",
        f"/user/installations?per_page=100&page={page}",
        await github.user_token(db, connection),
    )
    items = value.get("installations")
    if not isinstance(items, list):
        raise Problem(502, "GITHUB_AUTH_RESPONSE", "App 安装列表不完整。")
    return {
        "items": [
            {"id": item["id"], "account": item.get("account", {}).get("login", "")}
            for item in items
            if isinstance(item, dict) and str(item.get("app_id")) == github.settings.github_app_id
        ],
        "has_more": len(items) == 100,
        "page": page,
    }


@router.get("/installations/{installation_id}/repositories", response_model=RepositoryList)
async def repositories(
    installation_id: int,
    user: CurrentUser,
    db: Db,
    request: Request,
    page: Annotated[int, Query(ge=1, le=3)] = 1,
) -> dict[str, object]:
    if installation_id < 1:
        raise Problem(400, "GITHUB_INSTALLATION", "请选择有效安装。")
    connection = await db.scalar(
        select(GitHubConnection).where(GitHubConnection.user_id == user.id)
    )
    if connection is None:
        raise Problem(403, "GITHUB_REAUTHORIZE", "请先连接 GitHub。")
    github = client(request)
    value = await github.call(
        "GET",
        f"/user/installations/{installation_id}/repositories?per_page=100&page={page}",
        await github.user_token(db, connection),
    )
    items = value.get("repositories")
    if not isinstance(items, list):
        raise Problem(502, "GITHUB_AUTH_RESPONSE", "仓库列表不完整。")
    return {
        "items": [
            {"id": item["id"], "full_name": item["full_name"], "private": item.get("private", True)}
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("id"), int)
            and isinstance(item.get("full_name"), str)
        ],
        "has_more": len(items) == 100,
        "page": page,
    }


@router.post("/sources", response_model=SourceResponse, status_code=201)
async def connect(
    body: RepositoryChoice, user: CurrentUser, db: Db, request: Request
) -> SourceResponse:
    connection = await db.scalar(
        select(GitHubConnection).where(GitHubConnection.user_id == user.id)
    )
    if connection is None:
        raise Problem(403, "GITHUB_REAUTHORIZE", "请先连接 GitHub。")
    repository = repository_ref(body.repository)
    github = client(request)
    # A temporary unpersisted scope undergoes the same intersection checks as every worker call.
    draft = KnowledgeSource(
        user_id=user.id,
        external_ref=repository,
        github_connection_id=connection.id,
        github_repository_id=body.repository_id,
        github_installation_id=body.installation_id,
    )
    await github.source_token(db, draft)
    created = await db.scalar(
        insert(KnowledgeSource)
        .values(
            user_id=user.id,
            provider="github",
            external_ref=repository,
            read_scope=[repository],
            path_prefixes=body.path_prefixes,
            write_scope=[],
            status="CONNECTED",
            github_connection_id=connection.id,
            github_repository_id=body.repository_id,
            github_installation_id=body.installation_id,
        )
        .on_conflict_do_nothing(
            index_elements=[
                KnowledgeSource.user_id,
                KnowledgeSource.provider,
                KnowledgeSource.external_ref,
            ]
        )
        .returning(KnowledgeSource.id)
    )
    if created is None:
        existing = await db.scalar(
            select(KnowledgeSource)
            .where(
                KnowledgeSource.user_id == user.id,
                KnowledgeSource.provider == "github",
                KnowledgeSource.external_ref == repository,
            )
            .with_for_update()
        )
        assert existing is not None
        if existing.status not in {"DISCONNECTED", "REAUTH_REQUIRED"}:
            raise Problem(409, "SOURCE_EXISTS", "该仓库已有来源，请在原来源中操作。")
        existing.github_connection_id, existing.github_repository_id = (
            connection.id,
            body.repository_id,
        )
        existing.github_installation_id, existing.path_prefixes = (
            body.installation_id,
            body.path_prefixes,
        )
        existing.status, existing.write_scope = "CONNECTED", []
        existing.encrypted_credential, existing.encrypted_write_credential = None, None
        existing.version += 1
        await db.commit()
        return SourceResponse.model_validate(existing)
    row = await get_owned(db, KnowledgeSource, user.id, created)
    await db.commit()
    return SourceResponse.model_validate(row)


@router.put("/sources/{source_id}/write-permission", status_code=204)
async def grant_write(
    source_id: UUID, body: GitHubWritePermission, user: CurrentUser, db: Db, request: Request
) -> None:
    if not request.app.state.settings.writeback_enabled:
        raise Problem(403, "WRITEBACK_DISABLED", "部署尚未启用写回。")
    source = await get_owned(db, KnowledgeSource, user.id, source_id)
    await db.refresh(source, with_for_update=True)
    if source.status != "CONNECTED" or source.version != body.version:
        raise Problem(409, "SOURCE_CONFLICT", "来源已变化，请刷新后重新确认。")
    await client(request).source_token(db, source, write=True)
    source.write_scope, source.version = body.path_prefixes, source.version + 1
    source.encrypted_write_credential = None
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="WRITE_PERMISSION_GRANTED",
            object_type="source",
            object_id=str(source.id),
            summary_code="APP_SINGLE_REPOSITORY_SCOPE",
        )
    )
    await db.commit()


@router.delete("/connection", status_code=204)
async def disconnect(user: CurrentUser, db: Db) -> None:
    rows = await db.scalars(
        select(KnowledgeSource)
        .where(
            KnowledgeSource.user_id == user.id, KnowledgeSource.github_connection_id.is_not(None)
        )
        .order_by(KnowledgeSource.id)
        .with_for_update()
    )
    for source in rows:
        source.status, source.write_scope = "DISCONNECTED", []
        source.encrypted_credential, source.encrypted_write_credential = None, None
        source.version += 1
    await db.execute(
        update(Job)
        .where(
            Job.user_id == user.id,
            Job.source_id.in_(
                select(KnowledgeSource.id).where(
                    KnowledgeSource.user_id == user.id,
                    KnowledgeSource.github_connection_id.is_not(None),
                )
            ),
            Job.status.in_(["PENDING", "RUNNING"]),
        )
        .values(status="CANCELLED", lease_id=None, finished_at=datetime.now(UTC))
    )
    await db.refresh(user, with_for_update=True)
    user.github_auth_version += 1
    connection = await db.scalar(
        select(GitHubConnection).where(GitHubConnection.user_id == user.id).with_for_update()
    )
    if connection:
        connection.status, connection.encrypted_token, connection.encrypted_refresh = (
            "DISCONNECTED",
            None,
            None,
        )
    await db.execute(delete(GitHubOAuthState).where(GitHubOAuthState.user_id == user.id))
    await db.commit()
