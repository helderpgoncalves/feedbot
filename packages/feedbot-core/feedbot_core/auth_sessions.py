"""Server-side session helpers.

The dashboard / SPA cookie carries only an opaque ``session_id`` (32 bytes
url-safe). Validation is a DB lookup against the ``sessions`` table. Mutations
are a single UPDATE — no cookie crypto, no payload to sign.

Why server-side over the previous signed cookie:

- **Revocable.** ``POST /v1/auth/logout`` and ``POST /v1/auth/logout-all`` are
  cheap UPDATEs. The signed cookie was good until expiry, regardless of intent.
- **Auditable.** Every active session is visible in the DB — basis for a
  "Security" page that lists ``ip``, ``user_agent``, ``last_seen_at``.
- **Rotation-friendly.** New session ID issued on every login; old IDs are
  immediately invalidated. Blocks session fixation.

This module is deliberately small (~6 functions). It does no I/O outside of
the SQLAlchemy session it's handed; FastAPI routers call into it directly.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_core.models import Session as DbSession
from feedbot_core.models import User

#: Default lifetime of a session. Long enough to keep dashboards open across
#: a workweek; short enough that a forgotten session expires on its own.
DEFAULT_TTL = timedelta(days=14)

#: Length (bytes) of the random session id. 32 bytes = 256 bits of entropy.
ID_BYTES = 32


@dataclass(slots=True, frozen=True)
class SessionContext:
    """Lightweight view of a validated session, returned by ``lookup``."""

    session_id: str
    user: User


def _now() -> datetime:
    return datetime.now(UTC)


def new_session_id() -> str:
    """Allocate a fresh opaque session id.

    Public so callers can pre-generate the id (e.g. for cookie set-and-forget
    flows that issue the cookie before the DB write completes).
    """
    return secrets.token_urlsafe(ID_BYTES)


async def create(
    session: AsyncSession,
    *,
    user: User,
    user_agent: str | None = None,
    ip: str | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> DbSession:
    """Create a new session for ``user`` and return it.

    Caller is responsible for setting the resulting cookie on the response.
    """
    row = DbSession(
        id=new_session_id(),
        user_id=user.id,
        expires_at=_now() + ttl,
        user_agent=(user_agent or None),
        ip=(ip or None),
    )
    session.add(row)
    await session.flush()
    return row


async def lookup(session: AsyncSession, session_id: str) -> SessionContext | None:
    """Validate a cookie's ``session_id`` and return the active user.

    Returns ``None`` if the session does not exist, was revoked, or expired.
    Side-effect: bumps ``last_seen_at`` on every successful lookup.

    Implementation note: we issue a SELECT (not ``session.get``) so the row is
    refreshed from the database on every call. ``session.get`` would return
    the identity-map copy, which can be stale after a bulk-revoke UPDATE in
    the same SQLAlchemy session.
    """
    if not session_id:
        return None
    result = await session.execute(
        select(DbSession).where(DbSession.id == session_id).execution_options(populate_existing=True)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.revoked_at is not None:
        return None
    if row.expires_at < _now():
        return None

    user = await session.get(User, row.user_id)
    if user is None:
        # User was deleted while session was alive — treat as revoked.
        row.revoked_at = _now()
        await session.flush()
        return None

    row.last_seen_at = _now()
    return SessionContext(session_id=row.id, user=user)


async def revoke(session: AsyncSession, session_id: str) -> bool:
    """Revoke one session by id. Idempotent — returns False if not found / already revoked."""
    row = await session.get(DbSession, session_id)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    await session.flush()
    return True


async def revoke_all_for_user(session: AsyncSession, user_id: int) -> int:
    """Revoke every active session for ``user_id``. Returns count revoked.

    The bulk UPDATE bypasses the SQLAlchemy identity map. We pass
    ``synchronize_session='fetch'`` so any rows already loaded in the session
    pick up the new ``revoked_at`` immediately — without it a subsequent
    ``lookup`` in the same session would still see the cached row as active.
    """
    now = _now()
    result = await session.execute(
        update(DbSession)
        .where(DbSession.user_id == user_id, DbSession.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session="fetch")
    )
    await session.flush()
    return int(result.rowcount or 0)


async def list_active(session: AsyncSession, user_id: int) -> list[DbSession]:
    """Return active (non-revoked, non-expired) sessions for a user.

    Used by the "Security" page to let users see + revoke their own devices.
    """
    rows = await session.execute(
        select(DbSession)
        .where(
            DbSession.user_id == user_id,
            DbSession.revoked_at.is_(None),
            DbSession.expires_at > _now(),
        )
        .order_by(DbSession.last_seen_at.desc())
    )
    return list(rows.scalars())
