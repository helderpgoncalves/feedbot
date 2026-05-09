"""C1.1 + C1.2 — multi-tenant cloud signup.

Contract under test (TODO-CLOUD-V1.md C1):

    1. ``FEEDBOT_ALLOW_SIGNUP`` unset/false  >>> 404 (route appears absent).
    2. ``FEEDBOT_ALLOW_SIGNUP=true`` + new email  >>> 200, tenant + owner row
       created, magic-link issued, audit emits ``tenant.created`` and
       ``signup.attempt``.
    3. Same email twice  >>> both calls return generic 200 - duplicate
       detection must not leak via response shape or status code
       (anti-enumeration).
    4. Rate-limit 3/hour/IP - the fourth attempt returns 429.
    5. Tenant created has the user as ``OWNER``.

We mutate ``FEEDBOT_ALLOW_SIGNUP`` directly because ``is_signup_enabled``
re-reads the env on every call (intentional, see settings.py).

Note: email addresses are constructed at runtime from a constant local-part
plus the ``@`` symbol so that no editor / pre-commit sanitiser can rewrite
them to a placeholder like "[email protected]" mid-file.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from feedbot_core.models import AuditEvent, Role, Tenant, User
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_AT = chr(0x40)  # literal "@" - protected from rewrite by editor sanitisers
_DOMAIN = "example.com"


def _addr(local: str) -> str:
    return f"{local}{_AT}{_DOMAIN}"


@pytest.fixture
def signup_enabled() -> AsyncIterator[None]:
    prev = os.environ.get("FEEDBOT_ALLOW_SIGNUP")
    os.environ["FEEDBOT_ALLOW_SIGNUP"] = "true"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("FEEDBOT_ALLOW_SIGNUP", None)
        else:
            os.environ["FEEDBOT_ALLOW_SIGNUP"] = prev


@pytest.fixture
def signup_disabled() -> AsyncIterator[None]:
    prev = os.environ.get("FEEDBOT_ALLOW_SIGNUP")
    os.environ["FEEDBOT_ALLOW_SIGNUP"] = "false"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("FEEDBOT_ALLOW_SIGNUP", None)
        else:
            os.environ["FEEDBOT_ALLOW_SIGNUP"] = prev


@pytest_asyncio.fixture
async def reset_rate_limiter():
    """Slowapi keeps an in-memory bucket per (route, IP) - reset between
    tests so 3/hour is per-test, not per-suite.
    """
    from feedbot_api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.asyncio
async def test_signup_404_when_disabled(
    client: AsyncClient,
    signup_disabled,
    reset_rate_limiter,
) -> None:
    res = await client.post(
        "/v1/signup",
        json={"email": _addr("nope"), "tenant_name": "Acme"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_signup_creates_tenant_and_owner(
    client: AsyncClient,
    db_session: AsyncSession,
    signup_enabled,
    reset_rate_limiter,
) -> None:
    res = await client.post(
        "/v1/signup",
        json={"email": _addr("owner"), "tenant_name": "Acme Co"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"sent": True}

    user_row = await db_session.execute(
        select(User).where(User.email == _addr("owner"))
    )
    user = user_row.scalar_one()
    assert user.role == Role.OWNER

    tenant = await db_session.get(Tenant, user.tenant_id)
    assert tenant is not None
    assert tenant.name == "Acme Co"

    # Both audits fired in the right order.
    events_row = await db_session.execute(
        select(AuditEvent.event)
        .where(AuditEvent.event.in_(["signup.attempt", "tenant.created"]))
        .order_by(AuditEvent.created_at.asc())
    )
    events = list(events_row.scalars())
    assert events == ["signup.attempt", "tenant.created"]


@pytest.mark.asyncio
async def test_signup_falls_back_to_email_localpart(
    client: AsyncClient,
    db_session: AsyncSession,
    signup_enabled,
    reset_rate_limiter,
) -> None:
    """Empty tenant_name  >>> use the local-part of the email."""
    res = await client.post(
        "/v1/signup",
        json={"email": _addr("alice"), "tenant_name": ""},
    )
    assert res.status_code == 200

    user_row = await db_session.execute(
        select(User).where(User.email == _addr("alice"))
    )
    user = user_row.scalar_one()
    tenant = await db_session.get(Tenant, user.tenant_id)
    assert tenant is not None
    assert tenant.name == "alice"


@pytest.mark.asyncio
async def test_signup_duplicate_email_returns_generic_200(
    client: AsyncClient,
    db_session: AsyncSession,
    signup_enabled,
    reset_rate_limiter,
) -> None:
    """Anti-enumeration: a second signup for the same email looks identical
    to a fresh one from the outside, but does NOT create a second tenant.
    """
    first = await client.post(
        "/v1/signup",
        json={"email": _addr("dup"), "tenant_name": "First"},
    )
    assert first.status_code == 200

    second = await client.post(
        "/v1/signup",
        json={"email": _addr("dup"), "tenant_name": "Second"},
    )
    assert second.status_code == 200
    assert second.json() == {"sent": True}

    user_count = await db_session.execute(
        select(func.count())
        .select_from(User)
        .where(User.email == _addr("dup"))
    )
    assert user_count.scalar_one() == 1


@pytest.mark.asyncio
async def test_signup_rate_limited(
    client: AsyncClient,
    signup_enabled,
    reset_rate_limiter,
) -> None:
    """Burst more than 3 attempts/hour from the same IP  >>> 429."""
    for i in range(3):
        res = await client.post(
            "/v1/signup",
            json={"email": _addr(f"u{i}"), "tenant_name": "T"},
        )
        assert res.status_code == 200

    fourth = await client.post(
        "/v1/signup",
        json={"email": _addr("five"), "tenant_name": "Five"},
    )
    assert fourth.status_code == 429
