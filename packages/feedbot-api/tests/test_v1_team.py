"""Tests for /v1/tenant/users, /v1/invites/*, /v1/projects/{slug}/members."""

from __future__ import annotations

import pytest
from feedbot_core.models import Role
from feedbot_core.repos import (
    add_project_member,
    issue_invite,
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ─── /v1/tenant/users ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tenant_users_admin_only(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    await login_as(member)

    r = await client.get("/v1/tenant/users")

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_tenant_users_returns_all(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    await login_as(owner)

    r = await client.get("/v1/tenant/users")

    assert r.status_code == 200
    emails = sorted(u["email"] for u in r.json())
    assert emails == ["a@x.com", "m@x.com", "o@x.com"]


@pytest.mark.asyncio
async def test_patch_user_owner_unmodifiable(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    other_owner_target = await make_user(tenant=tenant, email="x@x.com", role=Role.OWNER)
    await login_as(owner)

    r = await client.patch(
        f"/v1/tenant/users/{other_owner_target.id}",
        json={"role": "admin"},
    )

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patch_user_cannot_grant_owner_via_role(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    target = await make_user(tenant=tenant, email="t@x.com", role=Role.MEMBER)
    await login_as(owner)

    # Pydantic refuses 'owner' at the schema level (pattern=admin|member).
    r = await client.patch(
        f"/v1/tenant/users/{target.id}",
        json={"role": "owner"},
    )

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_user_promotes_member_to_admin(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    target = await make_user(tenant=tenant, email="t@x.com", role=Role.MEMBER)
    await login_as(owner)

    r = await client.patch(
        f"/v1/tenant/users/{target.id}",
        json={"role": "admin"},
    )

    assert r.status_code == 200
    assert r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_delete_user_owner_unmodifiable(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    other_owner = await make_user(tenant=tenant, email="x@x.com", role=Role.OWNER)
    await login_as(owner)

    r = await client.delete(f"/v1/tenant/users/{other_owner.id}")

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_cannot_self_delete(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await login_as(admin)

    r = await client.delete(f"/v1/tenant/users/{admin.id}")

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_user_cross_tenant_returns_404(
    client: AsyncClient, make_tenant, make_user, login_as
):
    a = await make_tenant(name="A")
    b = await make_tenant(name="B")
    admin_a = await make_user(tenant=a, email="aa@x.com", role=Role.ADMIN)
    target_b = await make_user(tenant=b, email="bb@x.com", role=Role.MEMBER)
    await login_as(admin_a)

    r = await client.delete(f"/v1/tenant/users/{target_b.id}")

    assert r.status_code == 404


# ─── /v1/tenant/transfer-ownership ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_transfer_ownership_promotes_target_demotes_self(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    login_as,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    new_owner = await make_user(tenant=tenant, email="n@x.com", role=Role.ADMIN)
    await login_as(owner)

    r = await client.post(
        "/v1/tenant/transfer-ownership", json={"user_id": new_owner.id}
    )
    assert r.status_code == 204

    await db_session.refresh(owner)
    await db_session.refresh(new_owner)
    assert owner.role == Role.ADMIN
    assert new_owner.role == Role.OWNER


@pytest.mark.asyncio
async def test_transfer_ownership_admin_blocked(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    other = await make_user(tenant=tenant, email="o@x.com", role=Role.MEMBER)
    await login_as(admin)

    r = await client.post(
        "/v1/tenant/transfer-ownership", json={"user_id": other.id}
    )

    assert r.status_code == 403


# ─── /v1/invites ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_invite_admin_only(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    await login_as(member)

    r = await client.post(
        "/v1/invites", json={"email": "new@x.com", "role": "member"}
    )

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_invite_rejects_owner_role(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    # Pydantic rejects 'owner' at the schema layer.
    r = await client.post(
        "/v1/invites", json={"email": "new@x.com", "role": "owner"}
    )

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_invite_blocks_existing_tenant_user(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await make_user(tenant=tenant, email="existing@x.com", role=Role.MEMBER)
    await login_as(owner)

    r = await client.post(
        "/v1/invites", json={"email": "existing@x.com", "role": "member"}
    )

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_invite_unknown_project_slug(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    r = await client.post(
        "/v1/invites",
        json={"email": "new@x.com", "role": "member", "project_slug": "nope"},
    )

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_pending_invites_returns_only_unused(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    login_as,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    pending = await issue_invite(
        db_session,
        tenant_id=tenant.id,
        email="pending@x.com",
        role=Role.MEMBER,
        invited_by_user_id=owner.id,
    )
    await login_as(owner)

    r = await client.get("/v1/invites")
    assert r.status_code == 200
    emails = [inv["email"] for inv in r.json()]
    assert "pending@x.com" in emails
    assert any(inv["id"] == pending.id for inv in r.json())


@pytest.mark.asyncio
async def test_delete_invite_404_when_used(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    login_as,
):
    from datetime import UTC, datetime

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    invite = await issue_invite(
        db_session,
        tenant_id=tenant.id,
        email="used@x.com",
        role=Role.MEMBER,
        invited_by_user_id=owner.id,
    )
    invite.used_at = datetime.now(UTC)
    await db_session.flush()
    await login_as(owner)

    r = await client.delete(f"/v1/invites/{invite.id}")

    assert r.status_code == 404


# ─── /v1/invites/preview + accept (no auth) ────────────────────────────────


@pytest.mark.asyncio
async def test_invite_preview_404_for_invalid_token(client: AsyncClient):
    r = await client.get("/v1/invites/preview", params={"token": "definitely-wrong"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_invite_preview_returns_metadata(
    client: AsyncClient, db_session: AsyncSession, make_tenant, make_user
):
    tenant = await make_tenant(name="MyTenant")
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    invite = await issue_invite(
        db_session,
        tenant_id=tenant.id,
        email="invitee@x.com",
        role=Role.MEMBER,
        invited_by_user_id=owner.id,
    )

    r = await client.get(
        "/v1/invites/preview", params={"token": invite.token}
    )

    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "invitee@x.com"
    assert body["role"] == "member"
    assert body["tenant_name"] == "MyTenant"
    # Preview must not leak who invited.
    assert "invited_by" not in body


@pytest.mark.asyncio
async def test_invite_accept_creates_user_and_session(
    client: AsyncClient, db_session: AsyncSession, make_tenant, make_user
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    invite = await issue_invite(
        db_session,
        tenant_id=tenant.id,
        email="newjoiner@x.com",
        role=Role.MEMBER,
        invited_by_user_id=owner.id,
    )

    r = await client.post("/v1/invites/accept", json={"token": invite.token})
    assert r.status_code == 204

    # The accept response sets the fb_session cookie; subsequent /v1/me works.
    me = await client.get("/v1/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "newjoiner@x.com"


# ─── /v1/projects/{slug}/members ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_member_404_for_cross_tenant_user(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    a = await make_tenant(name="A")
    b = await make_tenant(name="B")
    admin_a = await make_user(tenant=a, email="aa@x.com", role=Role.OWNER)
    target_b = await make_user(tenant=b, email="bb@x.com", role=Role.MEMBER)
    await make_project(tenant=a, slug="demo")
    await login_as(admin_a)

    r = await client.post(
        "/v1/projects/demo/members", json={"user_id": target_b.id}
    )

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_add_member_409_when_already_member(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    project = await make_project(tenant=tenant, slug="demo")
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    await add_project_member(db_session, project.id, member.id)
    await login_as(admin)

    r = await client.post(
        "/v1/projects/demo/members", json={"user_id": member.id}
    )

    assert r.status_code == 409


@pytest.mark.asyncio
async def test_remove_member_404_when_not_member(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    r = await client.delete(f"/v1/projects/demo/members/{member.id}")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_members_returns_only_project_members(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    project = await make_project(tenant=tenant, slug="demo")
    member1 = await make_user(tenant=tenant, email="m1@x.com", role=Role.MEMBER)
    member2 = await make_user(tenant=tenant, email="m2@x.com", role=Role.MEMBER)
    other = await make_user(tenant=tenant, email="other@x.com", role=Role.MEMBER)  # NOT a member
    await add_project_member(db_session, project.id, member1.id)
    await add_project_member(db_session, project.id, member2.id)
    await login_as(admin)

    r = await client.get("/v1/projects/demo/members")

    assert r.status_code == 200
    emails = sorted(u["email"] for u in r.json())
    assert emails == ["m1@x.com", "m2@x.com"]
    assert other.email not in emails
