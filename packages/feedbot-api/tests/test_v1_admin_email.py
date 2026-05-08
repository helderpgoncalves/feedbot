"""HTTP tests for ``/v1/admin/email/*``.

Covers:

- Auth: anonymous → 401, member/admin → 403, owner → 200.
- Cloud builds: ``FEEDBOT_DEPLOYMENT=cloud`` → 404 on every endpoint.
- ``GET /config`` never returns the password, only ``has_password``.
- ``POST /config`` round-trip with tri-state password (``None``=keep,
  ``""``=clear, ``"x"``=set).
- ``POST /test`` returns ok=False with a structured error when SMTP
  isn't configured, and ok=True when the SMTP backend mock succeeds.

The orchestrator's host-side actions (env rewrite, ``compose
restart``) are stubbed out at the module level — we're testing the
HTTP contract here, not the orchestrator pipeline (covered already
in ``test_orchestrator.py``).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from feedbot_core.llm.crypto import encrypt_key
from feedbot_core.models import Role
from feedbot_core.repos import update_instance_config

# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def stub_orchestrator_side_effects(monkeypatch, tmp_path: Path):
    """Neutralise the host-side calls inside ``Orchestrator.apply_email``.

    - Redirect ``.env`` writes to a tmp path so we don't touch the
      repo root.
    - Mock ``compose.restart`` so no real ``docker compose`` runs.
    """
    from feedbot_api.orchestrator import compose

    monkeypatch.setenv("FEEDBOT_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setattr(compose, "restart", AsyncMock())
    yield


# ── auth ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config_requires_login(client):
    resp = await client.get("/v1/admin/email/config")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_config_member_forbidden(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    member = await make_user(tenant=tenant, email="m@x.com", role=Role.MEMBER)
    await login_as(member)

    resp = await client.get("/v1/admin/email/config")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_config_admin_forbidden(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await login_as(admin)

    resp = await client.get("/v1/admin/email/config")
    assert resp.status_code == 403  # require_owner, not require_tenant_admin


@pytest.mark.asyncio
async def test_get_config_owner_ok(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/email/config")
    assert resp.status_code == 200
    body = resp.json()
    # Empty / freshly-migrated DB defaults.
    assert body == {
        "host": None,
        "port": None,
        "user": None,
        "sender": None,
        "has_password": False,
        "configured": False,
    }


# ── cloud short-circuit ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cloud_deployment_returns_404(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    """``FEEDBOT_DEPLOYMENT=cloud`` must hide the orchestrator surface."""
    monkeypatch.setenv("FEEDBOT_DEPLOYMENT", "cloud")
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    for path in ("/v1/admin/email/config", "/v1/admin/email/test"):
        resp = await client.get(path) if path.endswith("config") else await client.post(
            path, json={"to": "a@b.com"}
        )
        assert resp.status_code == 404, path


# ── GET /config redacts password ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config_never_returns_password(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    await update_instance_config(
        db_session,
        smtp_host="smtp.x",
        smtp_port=587,
        smtp_user="u",
        smtp_password_encrypted=encrypt_key("supersecret"),
        smtp_from="from@x",
    )
    await db_session.commit()

    resp = await client.get("/v1/admin/email/config")
    body = resp.json()
    assert body["has_password"] is True
    assert body["configured"] is True
    # No password field at all on the wire.
    assert "password" not in body
    # Defensive: the secret value isn't in the serialized response.
    assert "supersecret" not in resp.text


# ── POST /config tri-state password ─────────────────────────────────


@pytest.mark.asyncio
async def test_post_config_sets_password(
    client,
    db_session,
    make_tenant,
    make_user,
    login_as,
    stub_orchestrator_side_effects,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post(
        "/v1/admin/email/config",
        json={
            "host": "smtp.x",
            "port": 587,
            "user": "u",
            "password": "pw",
            "sender": "from@x",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_password"] is True
    assert body["configured"] is True


@pytest.mark.asyncio
async def test_post_config_keep_password_with_none(
    client,
    db_session,
    make_tenant,
    make_user,
    login_as,
    stub_orchestrator_side_effects,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    # Seed an existing password.
    await update_instance_config(
        db_session,
        smtp_host="smtp.x",
        smtp_port=587,
        smtp_user="u",
        smtp_password_encrypted=encrypt_key("old-pw"),
        smtp_from="from@x",
    )
    await db_session.commit()

    # Update host but omit password — stored value must survive.
    resp = await client.post(
        "/v1/admin/email/config",
        json={
            "host": "smtp.new",
            "port": 587,
            "user": "u",
            "sender": "from@x",
            # no password key at all
        },
    )
    assert resp.status_code == 200
    assert resp.json()["host"] == "smtp.new"
    assert resp.json()["has_password"] is True


@pytest.mark.asyncio
async def test_post_config_clear_password_with_empty_string(
    client,
    db_session,
    make_tenant,
    make_user,
    login_as,
    stub_orchestrator_side_effects,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    await update_instance_config(
        db_session,
        smtp_host="smtp.x",
        smtp_port=587,
        smtp_password_encrypted=encrypt_key("old-pw"),
        smtp_from="from@x",
    )
    await db_session.commit()

    resp = await client.post(
        "/v1/admin/email/config",
        json={
            "host": "smtp.x",
            "port": 587,
            "sender": "from@x",
            "password": "",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["has_password"] is False


# ── POST /test ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_returns_error_when_unconfigured(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post(
        "/v1/admin/email/test", json={"to": "ops@example.com"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "not configured" in (body["error"] or "").lower()


@pytest.mark.asyncio
async def test_test_invokes_smtp_backend_when_configured(
    client,
    db_session,
    make_tenant,
    make_user,
    login_as,
    monkeypatch,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    await update_instance_config(
        db_session,
        smtp_host="smtp.x",
        smtp_port=587,
        smtp_user="u",
        smtp_password_encrypted=encrypt_key("pw"),
        smtp_from="from@x",
    )
    await db_session.commit()

    sent: list[dict] = []

    def fake_send(self, *, to, subject, body):
        sent.append({"to": to, "subject": subject})

    from feedbot_api import email_backend

    monkeypatch.setattr(email_backend.SMTPBackend, "send", fake_send)

    resp = await client.post(
        "/v1/admin/email/test", json={"to": "ops@example.com"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "error": None}
    assert sent == [{"to": "ops@example.com", "subject": "Feedbot SMTP test"}]


@pytest.mark.asyncio
async def test_test_returns_truncated_error_on_smtp_failure(
    client,
    db_session,
    make_tenant,
    make_user,
    login_as,
    monkeypatch,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    await update_instance_config(
        db_session,
        smtp_host="smtp.x",
        smtp_port=587,
        smtp_user="u",
        smtp_password_encrypted=encrypt_key("pw"),
        smtp_from="from@x",
    )
    await db_session.commit()

    long_err = "x" * 1000

    def fake_send(self, *, to, subject, body):
        raise RuntimeError(long_err)

    from feedbot_api import email_backend

    monkeypatch.setattr(email_backend.SMTPBackend, "send", fake_send)

    resp = await client.post(
        "/v1/admin/email/test", json={"to": "ops@example.com"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    # Truncated to <=240 chars per the router's _MAX_ERROR_LEN.
    assert body["error"] is not None
    assert len(body["error"]) <= 240
