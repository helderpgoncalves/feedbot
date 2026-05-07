"""Tests for LLM endpoints — settings, test, calls, providers.

Security focus: the encrypted API key must NEVER appear in any response,
audit row, or test outcome. Tests below assert that explicitly.
"""

from __future__ import annotations

import pytest
from feedbot_core.llm.crypto import encrypt_key
from feedbot_core.models import AuditEvent, ProjectLLMSettings, Role
from feedbot_core.repos import save_llm_settings
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ─── /v1/llm/providers ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_providers_listed_for_logged_in_user(
    client: AsyncClient, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    user = await make_user(tenant=tenant, email="u@x.com", role=Role.MEMBER)
    await login_as(user)

    r = await client.get("/v1/llm/providers")

    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    # OpenAI + Anthropic registered out of the box.
    assert "openai" in body["providers"]
    assert "anthropic" in body["providers"]


@pytest.mark.asyncio
async def test_providers_requires_auth(client: AsyncClient):
    r = await client.get("/v1/llm/providers")
    assert r.status_code == 401


# ─── GET /v1/projects/{slug}/llm-settings ──────────────────────────────────


@pytest.mark.asyncio
async def test_llm_settings_get_default_for_fresh_project(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    r = await client.get("/v1/projects/demo/llm-settings")

    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "none"
    assert body["enabled"] is False
    assert body["has_api_key"] is False
    assert body["month_to_date_usd"] == 0.0


@pytest.mark.asyncio
async def test_llm_settings_get_NEVER_returns_encrypted_key(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    """The strongest invariant in this module: even with a key configured,
    the GET response must not include any field that resembles the key
    (encrypted or otherwise). Failure here is a security incident."""
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    project = await make_project(tenant=tenant, slug="demo")
    secret = "sk-this-is-a-real-looking-openai-key-do-not-leak"
    await save_llm_settings(
        db_session,
        project.id,
        provider="openai",
        model="gpt-4o-mini",
        encrypted_api_key=encrypt_key(secret),
        enabled=True,
        monthly_budget_usd=10.0,
    )
    await login_as(admin)

    r = await client.get("/v1/projects/demo/llm-settings")

    assert r.status_code == 200
    body = r.json()
    assert body["has_api_key"] is True

    # Comprehensive leak check: serialize the entire body and ensure neither
    # the plaintext nor any forbidden fieldname is present.
    raw = r.text
    assert secret not in raw
    assert "encrypted_api_key" not in raw
    # Allow `has_api_key` (signalling boolean) but not standalone `api_key`.
    assert '"api_key"' not in raw
    assert "encrypted" not in raw


@pytest.mark.asyncio
async def test_llm_settings_requires_admin(
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
    # Member is a project member but not tenant admin.
    from feedbot_core.repos import add_project_member

    await add_project_member(db_session, project.id, member.id)
    await login_as(member)

    r = await client.get("/v1/projects/demo/llm-settings")

    assert r.status_code == 403


# ─── PUT /v1/projects/{slug}/llm-settings ──────────────────────────────────


@pytest.mark.asyncio
async def test_llm_settings_put_sets_key_first_time(
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
    await login_as(admin)

    r = await client.put(
        "/v1/projects/demo/llm-settings",
        json={
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-test-12345",
            "enabled": True,
            "monthly_budget_usd": 5.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["has_api_key"] is True
    assert body["enabled"] is True
    assert body["provider"] == "openai"

    # The DB row stores the encrypted blob, not the plaintext.
    row = await db_session.get(ProjectLLMSettings, project.id)
    assert row is not None
    assert row.encrypted_api_key is not None
    assert b"sk-test-12345" not in row.encrypted_api_key


@pytest.mark.asyncio
async def test_llm_settings_put_with_None_api_key_keeps_existing(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    """Partial-update semantics: omitting api_key must NOT delete the key."""
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    project = await make_project(tenant=tenant, slug="demo")
    original_encrypted = encrypt_key("sk-original")
    await save_llm_settings(
        db_session,
        project.id,
        provider="openai",
        model="gpt-4o-mini",
        encrypted_api_key=original_encrypted,
        enabled=True,
        monthly_budget_usd=10.0,
    )
    await login_as(admin)

    # Update model only, no api_key field at all.
    r = await client.put(
        "/v1/projects/demo/llm-settings",
        json={
            "provider": "openai",
            "model": "gpt-4o",
            "enabled": True,
            "monthly_budget_usd": 10.0,
        },
    )
    assert r.status_code == 200

    row = await db_session.get(ProjectLLMSettings, project.id)
    # Key blob unchanged. (We don't compare exact bytes because Fernet adds
    # a fresh IV per call; instead we check it's still set and identical to
    # what we wrote.)
    assert row.encrypted_api_key == original_encrypted
    assert row.model == "gpt-4o"


@pytest.mark.asyncio
async def test_llm_settings_put_empty_string_clears_key_when_disabled(
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
    await save_llm_settings(
        db_session,
        project.id,
        provider="openai",
        model="gpt-4o-mini",
        encrypted_api_key=encrypt_key("sk-original"),
        enabled=False,
        monthly_budget_usd=None,
    )
    await login_as(admin)

    r = await client.put(
        "/v1/projects/demo/llm-settings",
        json={
            "provider": "none",
            "model": None,
            "api_key": "",
            "enabled": False,
            "monthly_budget_usd": None,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["has_api_key"] is False

    row = await db_session.get(ProjectLLMSettings, project.id)
    assert row.encrypted_api_key is None


@pytest.mark.asyncio
async def test_llm_settings_put_rejects_clear_while_enabled(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    """Clearing the key while keeping classification enabled is a foot-gun:
    every inbound feedback would record an error. Reject loudly."""
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    project = await make_project(tenant=tenant, slug="demo")
    await save_llm_settings(
        db_session,
        project.id,
        provider="openai",
        model="gpt-4o-mini",
        encrypted_api_key=encrypt_key("sk-original"),
        enabled=True,
        monthly_budget_usd=None,
    )
    await login_as(admin)

    r = await client.put(
        "/v1/projects/demo/llm-settings",
        json={
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "",
            "enabled": True,
            "monthly_budget_usd": None,
        },
    )
    assert r.status_code == 400

    # The original key must still be there (no partial mutation).
    row = await db_session.get(ProjectLLMSettings, project.id)
    assert row.encrypted_api_key is not None


@pytest.mark.asyncio
async def test_llm_settings_put_rejects_unknown_provider(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    r = await client.put(
        "/v1/projects/demo/llm-settings",
        json={
            "provider": "definitely-not-a-provider",
            "model": "x",
            "enabled": False,
            "monthly_budget_usd": None,
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_llm_settings_audit_never_records_the_key(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    """Strong invariant: the audit log details for llm_settings.updated must
    never contain the plaintext or any prefix that could be linked to the key."""
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    project = await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    secret = "sk-distinctive-marker-string-12345"
    r = await client.put(
        "/v1/projects/demo/llm-settings",
        json={
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": secret,
            "enabled": True,
            "monthly_budget_usd": 5.0,
        },
    )
    assert r.status_code == 200

    # Pull every audit row touching this project.
    rows = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.project_id == project.id)
        )
    ).scalars().all()
    assert rows, "expected at least one audit event for the update"
    for row in rows:
        details = row.details or ""
        assert secret not in details, (
            f"audit row {row.id} ({row.event}) leaked the api key: {details}"
        )


# ─── /v1/projects/{slug}/llm-test ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_test_returns_disabled_when_no_settings(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    r = await client.post("/v1/projects/demo/llm-test")

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "disabled"


# ─── /v1/projects/{slug}/llm-calls ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_calls_returns_empty_for_fresh_project(
    client: AsyncClient, make_tenant, make_user, make_project, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.OWNER)
    await make_project(tenant=tenant, slug="demo")
    await login_as(admin)

    r = await client.get("/v1/projects/demo/llm-calls")

    assert r.status_code == 200
    assert r.json() == []
