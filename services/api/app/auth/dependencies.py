from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Problem
from app.core.security import digest_token
from app.persistence.models import AuthSession, OwnedEntity, User

bearer = HTTPBearer(auto_error=False)


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


Db = Annotated[AsyncSession, Depends(database_session)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


async def current_user(db: Db, credentials: Credentials, request: Request) -> User:
    token = credentials.credentials if credentials else request.cookies.get("frontier_session")
    if token is None or len(token) > 256:
        raise Problem(401, "AUTH_REQUIRED", "请先登录学习工作台。")
    if credentials is None and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
            raise Problem(403, "ORIGIN_DENIED", "请求来源未获授权，请从工作台操作。")
    request.state.session_digest = digest_token(token)
    result = await db.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_digest == request.state.session_digest,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
            AuthSession.auth_method.in_(
                ["PASSWORD", "DEVELOPMENT"]
                if (
                    request.app.state.settings.mock_auth
                    and request.app.state.settings.env != "production"
                )
                else ["PASSWORD"]
            ),
        )
    )
    if result is None:
        raise Problem(401, "SESSION_EXPIRED", "会话已失效，请重新登录。")
    return result


CurrentUser = Annotated[User, Depends(current_user)]


async def get_owned[Owned: OwnedEntity](
    db: AsyncSession, model: type[Owned], user_id: UUID, object_id: UUID
) -> Owned:
    result = await db.scalar(select(model).where(model.id == object_id, model.user_id == user_id))
    if result is None:
        # Do not reveal whether another user's object exists.
        raise Problem(404, "NOT_FOUND", "资源不存在或你没有访问权限。")
    return result
