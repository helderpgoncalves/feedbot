import hmac
import os
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends, Header, HTTPException, Request, status
from feedbot_core.db import make_engine, make_sessionmaker
from feedbot_core.models import ApiKey, Project
from feedbot_core.repos import authenticate_api_key
from feedbot_core.settings import CoreSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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


async def require_session_user(request: Request) -> str:
    email = request.session.get("email")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return email


async def require_bot_token(authorization: str | None = Header(default=None)) -> None:
    """Constant-time check of the shared bot secret. Used to authorize /v1/internal/*.

    Bot token is server-side only — it is *never* exposed to the user, browser, or MCP.
    """
    expected = os.getenv("FEEDBOT_BOT_TOKEN", "")
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot ingestion disabled")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bot token")
    raw = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(raw, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bot token")
