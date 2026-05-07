"""Tests for the JSON auth endpoints — /v1/auth/* and /v1/me."""

from __future__ import annotations

import pytest
from feedbot_core import auth_sessions
from feedbot_core.models import Role
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ─── /v1/me ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    r = await client.get("/v1/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_identity_for_logged_in_user(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant(name="Acme")
    owner = await make_user(tenant=tenant, email="owner@acme.com", role=Role.OWNER)
    await login_as(owner)

    r = await client.get("/v1/me")

    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "owner@acme.com"
    assert body["user"]["role"] == "owner"
    assert body["user"]["tenant_id"] == tenant.id
    assert body["tenant"]["name"] == "Acme"
    assert body["projects"] == []  # owner without any projects yet
    assert body["is_setup_complete"] is True


@pytest.mark.asyncio
async def test_me_lists_only_visible_projects_for_member(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    tenant = await make_tenant()
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    visible = await make_project(tenant=tenant, slug="visible", name="Visible")
    _hidden = await make_project(tenant=tenant, slug="hidden", name="Hidden")

    # Add member to `visible` only.
    from feedbot_core.repos import add_project_member

    await add_project_member(db_session, visible.id, member.id)
    await login_as(member)

    r = await client.get("/v1/me")

    body = r.json()
    slugs = [p["slug"] for p in body["projects"]]
    assert slugs == ["visible"]


# ─── /v1/auth/logout ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_revokes_session_and_clears_cookie(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    login_as,
):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="u@x.com")
    await login_as(user)

    # Currently authenticated.
    assert (await client.get("/v1/me")).status_code == 200

    r = await client.post("/v1/auth/logout")
    assert r.status_code == 204

    # The set-cookie deletion is sent in the response; httpx applies it.
    assert (await client.get("/v1/me")).status_code == 401


@pytest.mark.asyncio
async def test_logout_when_already_logged_out_is_noop(client: AsyncClient):
    r = await client.post("/v1/auth/logout")
    assert r.status_code == 204


# ─── /v1/auth/logout-all ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_all_revokes_every_session(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    login_as,
):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="u@x.com")

    # Two extra "phantom" sessions on this user to verify they're revoked too.
    extra1 = await auth_sessions.create(db_session, user=user)
    extra2 = await auth_sessions.create(db_session, user=user)
    await db_session.flush()

    await login_as(user)

    r = await client.post("/v1/auth/logout-all")
    assert r.status_code == 204

    # Current session is gone.
    assert (await client.get("/v1/me")).status_code == 401

    # The phantom sessions are also gone.
    assert await auth_sessions.lookup(db_session, extra1.id) is None
    assert await auth_sessions.lookup(db_session, extra2.id) is None


# ─── /v1/auth/sessions ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sessions_lists_only_active_with_current_marked(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    login_as,
):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="u@x.com")

    other = await auth_sessions.create(db_session, user=user, ip="9.9.9.9")
    revoked = await auth_sessions.create(db_session, user=user)
    await auth_sessions.revoke(db_session, revoked.id)
    await db_session.flush()

    await login_as(user)

    r = await client.get("/v1/auth/sessions")
    assert r.status_code == 200
    rows = r.json()

    ids = {row["id"]: row for row in rows}
    # Current login + the unrevoked extra; not the revoked one.
    assert other.id in ids
    assert revoked.id not in ids
    assert any(row["is_current"] for row in rows), "exactly one row should be is_current"
    assert sum(1 for row in rows if row["is_current"]) == 1


# ─── /v1/setup-status + /v1/setup ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_setup_status_required_when_db_empty(client: AsyncClient):
    r = await client.get("/v1/setup-status")
    assert r.status_code == 200
    assert r.json() == {"required": True}


@pytest.mark.asyncio
async def test_setup_status_not_required_after_bootstrap(
    client: AsyncClient, make_tenant, make_user
):
    tenant = await make_tenant()
    await make_user(tenant=tenant, email="someone@x.com", role=Role.OWNER)

    r = await client.get("/v1/setup-status")
    assert r.status_code == 200
    assert r.json() == {"required": False}


@pytest.mark.asyncio
async def test_setup_creates_owner_when_db_empty(client: AsyncClient):
    r = await client.post(
        "/v1/setup",
        json={"email": "founder@x.com", "tenant_name": "Acme"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "founder@x.com"
    # On the test deployment FEEDBOT_BASE_URL is http://, so the console
    # backend is considered "safe" and we report delivered=True with no
    # fallback link. Production-HTTPS-without-SMTP is covered separately.
    assert body["delivered"] is True
    assert body["fallback_link"] is None

    # Second call must 410 — bootstrap is one-shot.
    r2 = await client.post(
        "/v1/setup",
        json={"email": "intruder@x.com", "tenant_name": ""},
    )
    assert r2.status_code == 410


@pytest.mark.asyncio
async def test_setup_410_when_users_already_exist(
    client: AsyncClient, make_tenant, make_user
):
    tenant = await make_tenant()
    await make_user(tenant=tenant, email="existing@x.com", role=Role.OWNER)

    r = await client.post(
        "/v1/setup",
        json={"email": "second@x.com", "tenant_name": ""},
    )
    assert r.status_code == 410
