import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.auth.dependencies import CurrentUser, Db
from app.auth.passwords import (
    PasswordRequest,
    RecoveryRequest,
    password_hash,
    password_matches,
    rate_limit,
    recovery_matches,
)
from app.core.errors import Problem
from app.core.security import digest_token
from app.persistence.models import AuditEvent, AuthSession, Job, PasswordCredential, User

router = APIRouter(prefix="/auth", tags=["Auth"])


class MockLoginRequest(BaseModel):
    identity: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9@._+-]+$")
    client: Literal["web", "extension"] = "extension"


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user_id: UUID
    development_only: bool = True


class UserResponse(BaseModel):
    id: UUID
    identity: str


class AccountSession(BaseModel):
    access_token: str | None
    user_id: UUID
    expires_at: datetime
    recovery_code: str | None = Field(default=None, repr=False)


class RecoveryResponse(BaseModel):
    recovery_code: str = Field(repr=False)


class AuthOptions(BaseModel):
    mock_login: bool
    password_login: bool


@router.get("/options", response_model=AuthOptions)
async def auth_options(request: Request) -> AuthOptions:
    return AuthOptions(
        password_login=request.app.state.settings.password_auth,
        mock_login=request.app.state.settings.mock_auth
        and request.app.state.settings.env != "production",
    )


@router.post("/mock-login", response_model=LoginResponse)
async def mock_login(
    body: MockLoginRequest, request: Request, response: Response, db: Db
) -> LoginResponse:
    if not request.app.state.settings.mock_auth or request.app.state.settings.env == "production":
        raise Problem(404, "MOCK_AUTH_DISABLED", "模拟登录未开启。")
    # Explicit development endpoint: never enabled in production.
    formal_identity = "account:" + unicodedata.normalize("NFKC", body.identity).casefold()
    if await db.scalar(select(User.id).where(User.identity == formal_identity)):
        raise Problem(403, "PASSWORD_REQUIRED", "此账号需要使用密码登录。")
    await db.execute(
        insert(User)
        .values(identity=body.identity)
        .on_conflict_do_nothing(index_elements=[User.identity])
    )
    user = await db.scalar(select(User).where(User.identity == body.identity))
    assert user is not None
    await db.refresh(user, with_for_update=True)
    if await db.scalar(select(PasswordCredential.id).where(PasswordCredential.user_id == user.id)):
        raise Problem(403, "PASSWORD_REQUIRED", "此账号需要使用密码登录。")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(minutes=60)
    db.add(AuthSession(user_id=user.id, token_digest=digest_token(token), expires_at=expires))
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="LOGIN",
            object_type="user",
            object_id=str(user.id),
            summary_code="DEVELOPMENT_SESSION",
        )
    )
    await db.commit()
    if body.client == "web":
        response.set_cookie(
            "frontier_session",
            token,
            max_age=3600,
            httponly=True,
            secure=request.app.state.settings.env == "production",
            samesite="strict",
            path="/api/v1",
        )
    return LoginResponse(access_token=token, expires_at=expires, user_id=user.id)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse(id=user.id, identity=user.public_identity)


@router.post("/logout", status_code=204)
async def logout(user: CurrentUser, db: Db, request: Request) -> Response:
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.token_digest == request.state.session_digest,
        )
        .values(revoked_at=datetime.now(UTC))
    )
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="LOGOUT",
            object_type="user",
            object_id=str(user.id),
            summary_code="SESSION_REVOKED",
        )
    )
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie("frontier_session", path="/api/v1", httponly=True, samesite="strict")
    return response


def check_password_enabled(request: Request, client: str) -> None:
    if not request.app.state.settings.password_auth:
        raise Problem(404, "PASSWORD_AUTH_DISABLED", "账号登录尚未开启。")
    # Origin is mandatory for cookie-bearing browser login, signup and recovery requests.
    origin = request.headers.get("origin")
    if (
        client == "web"
        and origin not in request.app.state.settings.allowed_origins
        and (origin is not None or request.app.state.settings.env == "production")
    ):
        raise Problem(403, "ORIGIN_DENIED", "请从已授权的工作台登录。")


async def account_session(
    db: Db,
    request: Request,
    response: Response,
    user: User,
    client: str,
    recovery: str | None = None,
) -> AccountSession:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(hours=1)
    db.add(
        AuthSession(
            user_id=user.id,
            token_digest=digest_token(token),
            expires_at=expires,
            auth_method="PASSWORD",
        )
    )
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="LOGIN",
            object_type="user",
            object_id=str(user.id),
            summary_code="PASSWORD_SESSION",
        )
    )
    await db.commit()
    if client == "web":
        response.set_cookie(
            "frontier_session",
            token,
            max_age=3600,
            httponly=True,
            secure=request.app.state.settings.env == "production",
            samesite="strict",
            path="/api/v1",
        )
    return AccountSession(
        access_token=token if client == "extension" else None,
        user_id=user.id,
        expires_at=expires,
        recovery_code=recovery,
    )


@router.post("/register", response_model=AccountSession, status_code=201)
async def register(
    body: PasswordRequest, request: Request, response: Response, db: Db
) -> AccountSession:
    check_password_enabled(request, body.client)
    await rate_limit(db, request, body.identity)
    hashed = await password_hash(body.password, request.app.state.password_slots)
    identity = await db.scalar(
        insert(User)
        .values(identity="account:" + body.identity)
        .on_conflict_do_nothing(index_elements=[User.identity])
        .returning(User.id)
    )
    if identity is None:
        raise Problem(409, "IDENTITY_UNAVAILABLE", "此用户名不可用，请选择其他名称或登录。")
    user = await db.get(User, identity)
    assert user is not None
    recovery = secrets.token_urlsafe(32)
    db.add(
        PasswordCredential(
            user_id=user.id, password_hash=hashed, recovery_digest=digest_token(recovery)
        )
    )
    return await account_session(db, request, response, user, body.client, recovery)


@router.post("/login", response_model=AccountSession)
async def login(
    body: PasswordRequest, request: Request, response: Response, db: Db
) -> AccountSession:
    check_password_enabled(request, body.client)
    await rate_limit(db, request, body.identity)
    user = await db.scalar(select(User).where(User.identity == "account:" + body.identity))
    credential = (
        await db.scalar(select(PasswordCredential).where(PasswordCredential.user_id == user.id))
        if user
        else None
    )
    if (
        not await password_matches(
            body.password,
            credential.password_hash if credential else None,
            request.app.state.password_slots,
        )
        or user is None
    ):
        raise Problem(401, "LOGIN_FAILED", "用户名或密码不正确。")
    # Lock the parent before credentials, matching account deletion.
    locked = await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    if locked is None:
        raise Problem(401, "LOGIN_FAILED", "账号已变化，请重新登录。")
    # Re-check under the credential lock so a concurrent recovery invalidates old passwords.
    if credential is not None:
        original = credential.password_hash
        await db.refresh(credential, with_for_update=True)
        if credential.password_hash != original:
            raise Problem(401, "LOGIN_FAILED", "凭据已变化，请重新登录。")
    return await account_session(db, request, response, user, body.client)


@router.post("/recover", response_model=RecoveryResponse)
async def recover(body: RecoveryRequest, request: Request, db: Db) -> RecoveryResponse:
    check_password_enabled(request, body.client)
    await rate_limit(db, request, body.identity)
    user = await db.scalar(select(User).where(User.identity == "account:" + body.identity))
    if user is not None:
        list(
            await db.scalars(
                select(Job)
                .where(Job.user_id == user.id, Job.status.in_(["PENDING", "RUNNING"]))
                .order_by(Job.id)
                .with_for_update()
            )
        )
        locked = await db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        if locked is None:
            raise Problem(401, "RECOVERY_FAILED", "账号已变化，请重新操作。")
        await db.refresh(user)
    credential = (
        await db.scalar(
            select(PasswordCredential)
            .where(PasswordCredential.user_id == user.id)
            .with_for_update()
        )
        if user
        else None
    )
    valid = recovery_matches(body.recovery_code, credential.recovery_digest if credential else None)
    hashed = await password_hash(body.password, request.app.state.password_slots)
    if not valid or credential is None or user is None:
        raise Problem(401, "RECOVERY_FAILED", "用户名或恢复码不正确，或恢复码已使用。")
    await db.execute(
        update(Job)
        .where(Job.user_id == user.id, Job.status.in_(["PENDING", "RUNNING"]))
        .values(status="CANCELLED", lease_id=None, finished_at=datetime.now(UTC))
    )
    user.github_auth_version += 1
    replacement = secrets.token_urlsafe(32)
    credential.password_hash, credential.recovery_digest = hashed, digest_token(replacement)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id)
        .values(revoked_at=datetime.now(UTC))
    )
    db.add(
        AuditEvent(
            user_id=user.id,
            operation="ACCOUNT_RECOVERED",
            object_type="user",
            object_id=str(user.id),
            summary_code="SESSIONS_REVOKED",
        )
    )
    await db.commit()
    return RecoveryResponse(recovery_code=replacement)
