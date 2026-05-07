"""FastAPI dependencies — sessions, authn, authz."""

from __future__ import annotations

import hmac
import os
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends, Header, HTTPException, Request, status
from feedbot_core import auth_sessions
from feedbot_core.db import make_engine, make_sessionmaker
from feedbot_core.models import ApiKey, Project, Role, User
from feedbot_core.repos import (
    authenticate_api_key,
    get_project_by_slug,
    user_can_access_project,
)
from feedbot_core.settings import CoreSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

#: Cookie name carrying the server-side session id. Mirrored in routers/auth.py
#: deliberately rather than imported, to keep deps.py free of circular imports.
SESSION_COOKIE = "fb_session"


@lru_cache
def _engine():
    return make_engine(CoreSettings())


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(_engine())


async def get_session() -> AsyncIterator[AsyncSession]:
    sm = _sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─── REST API auth (bearer fbk_*) ───────────────────────────────────────────


async def get_api_key(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    raw = authorization.split(" ", 1)[1].strip()
    key = await authenticate_api_key(session, raw)
    if not key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
    return key


async def get_project_from_key(
    key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
) -> Project:
    project = await session.get(Project, key.project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


# ─── Bot token (shared secret, server-side only) ────────────────────────────


async def require_bot_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("FEEDBOT_BOT_TOKEN", "")
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot ingestion disabled")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bot token")
    raw = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(raw, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bot token")


# ─── Dashboard auth (session cookie + DB lookup) ────────────────────────────


async def require_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    """Resolve the logged-in user from the server-side session cookie.

    The cookie ``fb_session`` carries an opaque token; ``auth_sessions.lookup``
    validates it against the ``sessions`` table and returns the user (bumping
    ``last_seen_at`` as a side effect). Raises 401 if no cookie, expired,
    revoked, or the user has been deleted.
    """
    sid = request.cookies.get(SESSION_COOKIE)
    ctx = await auth_sessions.lookup(session, sid or "")
    if ctx is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return ctx.user


async def require_tenant_admin(user: User = Depends(require_user)) -> User:
    """Owner or admin. Used for tenant-wide actions (invite, create project, etc.)."""
    if user.role not in (Role.OWNER, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return user


async def require_owner(user: User = Depends(require_user)) -> User:
    """Owner only. Used for actions that affect the owner itself."""
    if user.role != Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner role required")
    return user


async def require_project_access(
    slug: str,
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> tuple[User, Project]:
    """Resolve a project by slug and ensure the current user can see it."""
    project = await get_project_by_slug(session, user.tenant_id, slug)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    if not await user_can_access_project(session, user, project):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return user, project


async def require_project_admin(
    pair: tuple[User, Project] = Depends(require_project_access),
) -> tuple[User, Project]:
    """Mutating ops on the project (keys, chat-links, members) require admin role."""
    user, project = pair
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return user, project
