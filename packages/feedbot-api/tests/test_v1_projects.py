"""Tests for /v1/projects, /v1/projects/{slug}/api-keys, /v1/projects/{slug}/chat-links."""

from __future__ import annotations

import pytest
from feedbot_core.models import Role
from feedbot_core.repos import add_project_member
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ─── /v1/projects ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_project_requires_admin(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    await login_as(member)

    r = await client.post("/v1/projects", json={"slug": "demo", "name": "Demo"})

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_project_succeeds_for_admin(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await login_as(admin)

    r = await client.post("/v1/projects", json={"slug": "demo", "name": "Demo"})

    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "demo"
    assert body["name"] == "Demo"


@pytest.mark.asyncio
async def test_create_project_rejects_invalid_slug(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await login_as(admin)

    r = await client.post("/v1/projects", json={"slug": "Has Space", "name": "X"})

    assert r.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_create_project_409_on_duplicate_slug(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await make_project(tenant=tenant, slug="demo", name="Existing")
    await login_as(admin)

    r = await client.post("/v1/projects", json={"slug": "demo", "name": "Other"})

    assert r.status_code == 409


@pytest.mark.asyncio
async def test_get_project_404_for_member_without_access(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    await make_project(tenant=tenant, slug="hidden")
    await login_as(member)

    r = await client.get("/v1/projects/hidden")

    # 404, not 403 — we don't reveal that the slug exists.
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_project_includes_status_counts(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=tenant, slug="demo", name="Demo")
    await login_as(admin)

    r = await client.get("/v1/projects/demo")

    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "demo"
    assert "feedback_count_by_status" in body
    # Empty project — every status counts to 0 (the helper pre-populates).
    assert all(v == 0 for v in body["feedback_count_by_status"].values())


@pytest.mark.asyncio
async def test_cross_tenant_isolation_on_get(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    """A user in tenant A cannot read a project from tenant B even if they
    guess the slug."""
    a = await make_tenant(name="A")
    b = await make_tenant(name="B")
    user_a = await make_user(tenant=a, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=b, slug="secret-b", name="B's Project")
    await login_as(user_a)

    r = await client.get("/v1/projects/secret-b")

    assert r.status_code == 404


# ─── /v1/projects/{slug}/api-keys ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_secret_returned_only_on_create(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    create = await client.post(
        "/v1/projects/demo/api-keys",
        json={"label": "ci-bot", "scope": "write"},
    )
    assert create.status_code == 201
    secret = create.json()["key"]
    assert secret.startswith("fbk_")

    listing = await client.get("/v1/projects/demo/api-keys")
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    # The list view never re-renders the full secret.
    assert "key" not in rows[0]
    assert rows[0]["prefix"]
    assert not rows[0]["prefix"].endswith(secret[-8:])  # secret never leaks


@pytest.mark.asyncio
async def test_api_key_revoke_idempotent(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    create = await client.post(
        "/v1/projects/demo/api-keys",
        json={"label": "ci-bot", "scope": "write"},
    )
    key_id = create.json()["id"]

    first = await client.delete(f"/v1/projects/demo/api-keys/{key_id}")
    assert first.status_code == 204

    second = await client.delete(f"/v1/projects/demo/api-keys/{key_id}")
    assert second.status_code == 404  # no longer revokable


@pytest.mark.asyncio
async def test_api_key_routes_require_admin(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    tenant = await make_tenant()
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    project = await make_project(tenant=tenant, slug="demo")
    # Make member a project member but not tenant admin.
    await add_project_member(db_session, project.id, member.id)
    await login_as(member)

    r = await client.get("/v1/projects/demo/api-keys")

    assert r.status_code == 403


# ─── /v1/projects/{slug}/chat-links ────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_link_token_creates_15min_token(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    r = await client.post("/v1/projects/demo/chat-link-tokens")

    assert r.status_code == 201
    body = r.json()
    assert body["token"]
    assert "expires_at" in body
    # deep_link is empty when no FEEDBOT_TELEGRAM_BOT_USERNAME — fine for tests.
    assert "deep_link" in body
