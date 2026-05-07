"""Tests for the server-side session helpers in feedbot_core.auth_sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from feedbot_core import auth_sessions
from feedbot_core.models import Role
from sqlalchemy.ext.asyncio import AsyncSession

# ─── auth_sessions.create / lookup / revoke ────────────────────────────────


@pytest.mark.asyncio
async def test_create_returns_active_session(db_session: AsyncSession, make_tenant, make_user):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="me@x.com", role=Role.OWNER)

    sess = await auth_sessions.create(
        db_session, user=user, user_agent="UA-1", ip="1.2.3.4"
    )

    assert sess.id  # opaque token
    assert sess.user_id == user.id
    assert sess.user_agent == "UA-1"
    assert sess.ip == "1.2.3.4"
    assert sess.revoked_at is None
    assert sess.expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_lookup_resolves_active_session(db_session: AsyncSession, make_tenant, make_user):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="x@x.com")
    sess = await auth_sessions.create(db_session, user=user)

    ctx = await auth_sessions.lookup(db_session, sess.id)

    assert ctx is not None
    assert ctx.user.id == user.id
    assert ctx.session_id == sess.id


@pytest.mark.asyncio
async def test_lookup_returns_none_for_unknown_id(db_session: AsyncSession):
    assert await auth_sessions.lookup(db_session, "doesnotexist") is None
    assert await auth_sessions.lookup(db_session, "") is None


@pytest.mark.asyncio
async def test_lookup_returns_none_when_revoked(db_session: AsyncSession, make_tenant, make_user):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="x@x.com")
    sess = await auth_sessions.create(db_session, user=user)

    revoked = await auth_sessions.revoke(db_session, sess.id)
    assert revoked is True

    assert await auth_sessions.lookup(db_session, sess.id) is None


@pytest.mark.asyncio
async def test_lookup_returns_none_when_expired(db_session: AsyncSession, make_tenant, make_user):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="x@x.com")
    sess = await auth_sessions.create(db_session, user=user)

    sess.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    assert await auth_sessions.lookup(db_session, sess.id) is None


@pytest.mark.asyncio
async def test_revoke_is_idempotent(db_session: AsyncSession, make_tenant, make_user):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="x@x.com")
    sess = await auth_sessions.create(db_session, user=user)

    assert await auth_sessions.revoke(db_session, sess.id) is True
    assert await auth_sessions.revoke(db_session, sess.id) is False  # already revoked
    assert await auth_sessions.revoke(db_session, "not-a-real-id") is False


@pytest.mark.asyncio
async def test_revoke_all_revokes_only_the_target_users_sessions(
    db_session: AsyncSession, make_tenant, make_user
):
    tenant = await make_tenant()
    alice = await make_user(tenant=tenant, email="alice@x.com")
    bob = await make_user(tenant=tenant, email="bob@x.com")

    a1 = await auth_sessions.create(db_session, user=alice)
    a2 = await auth_sessions.create(db_session, user=alice)
    b1 = await auth_sessions.create(db_session, user=bob)

    revoked = await auth_sessions.revoke_all_for_user(db_session, alice.id)
    assert revoked == 2

    # Both of alice's sessions are gone, bob's survives.
    assert await auth_sessions.lookup(db_session, a1.id) is None
    assert await auth_sessions.lookup(db_session, a2.id) is None
    assert await auth_sessions.lookup(db_session, b1.id) is not None


@pytest.mark.asyncio
async def test_list_active_excludes_revoked_and_expired(
    db_session: AsyncSession, make_tenant, make_user
):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="x@x.com")

    s_active = await auth_sessions.create(db_session, user=user)
    s_revoked = await auth_sessions.create(db_session, user=user)
    s_expired = await auth_sessions.create(db_session, user=user)

    await auth_sessions.revoke(db_session, s_revoked.id)
    s_expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    active = await auth_sessions.list_active(db_session, user.id)

    ids = [s.id for s in active]
    assert s_active.id in ids
    assert s_revoked.id not in ids
    assert s_expired.id not in ids
