"""HTTP tests for ``/v1/admin/system/*``.

Same shape as the email/bot/proxy tests. ``docker compose`` and
``systemctl`` / ``launchctl`` calls are stubbed at the orchestrator
submodules so we never shell out.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from feedbot_core.models import Role

# ── auth ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_requires_login(client):
    resp = await client.get("/v1/admin/system/status")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_status_admin_forbidden(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await login_as(admin)
    resp = await client.get("/v1/admin/system/status")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cloud_deployment_returns_404(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    monkeypatch.setenv("FEEDBOT_DEPLOYMENT", "cloud")
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)
    resp = await client.get("/v1/admin/system/status")
    assert resp.status_code == 404


# ── /status ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_parses_compose_ps_array(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    """Older compose emits a single JSON array."""
    from feedbot_api.orchestrator import compose

    fake_stdout = (
        "["
        '{"Service":"api","State":"running","Image":"feedbot-api","Status":"Up 5m"},'
        '{"Service":"db","State":"running","Image":"postgres:16","Status":"Up 5m"}'
        "]"
    )
    monkeypatch.setattr(
        compose,
        "ps",
        AsyncMock(
            return_value=compose.ComposeResult(
                args=["ps"], returncode=0, stdout=fake_stdout, stderr=""
            )
        ),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/system/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert {s["name"] for s in body["services"]} == {"api", "db"}


@pytest.mark.asyncio
async def test_status_parses_compose_ps_ndjson(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    """Newer compose emits one JSON object per line."""
    from feedbot_api.orchestrator import compose

    fake_stdout = (
        '{"Service":"api","State":"running","Image":"x","Status":"Up"}\n'
        '{"Service":"web","State":"exited","Image":"y","Status":"Exited"}'
    )
    monkeypatch.setattr(
        compose,
        "ps",
        AsyncMock(
            return_value=compose.ComposeResult(
                args=["ps"], returncode=0, stdout=fake_stdout, stderr=""
            )
        ),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/system/status")
    assert resp.status_code == 200
    body = resp.json()
    # One service is exited, so overall ok is False.
    assert body["ok"] is False
    states = {s["name"]: s["state"] for s in body["services"]}
    assert states == {"api": "running", "web": "exited"}


@pytest.mark.asyncio
async def test_status_returns_200_with_error_on_compose_failure(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import compose

    monkeypatch.setattr(
        compose,
        "ps",
        AsyncMock(
            side_effect=compose.ComposeError(
                args=["ps"], returncode=1, stderr="docker not running"
            )
        ),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/system/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["services"] == []
    assert "docker" in (body["error"] or "")


# ── /restart ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restart_calls_compose(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import compose

    restart = AsyncMock()
    monkeypatch.setattr(compose, "restart", restart)

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post("/v1/admin/system/restart", json={"service": "api"})
    assert resp.status_code == 204
    restart.assert_awaited_once_with("api")


@pytest.mark.asyncio
async def test_restart_502_on_compose_error(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import compose

    monkeypatch.setattr(
        compose,
        "restart",
        AsyncMock(
            side_effect=compose.ComposeError(
                args=["restart", "api"], returncode=1, stderr="boom"
            )
        ),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post("/v1/admin/system/restart", json={"service": "api"})
    assert resp.status_code == 502


# ── /autostart ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_autostart_status_reflects_orchestrator(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import autostart

    monkeypatch.setattr(
        autostart,
        "status",
        lambda: autostart.AutostartStatus(
            platform=autostart.Platform.LINUX_SYSTEMD,
            enabled=True,
            unit_path="/etc/systemd/system/feedbot.service",
        ),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/system/autostart")
    assert resp.status_code == 200
    body = resp.json()
    assert body["platform"] == "linux-systemd"
    assert body["enabled"] is True


@pytest.mark.asyncio
async def test_autostart_toggle_calls_orchestrator(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import autostart

    enable = MagicMock(
        return_value=autostart.AutostartStatus(
            platform=autostart.Platform.MACOS_LAUNCHD,
            enabled=True,
            unit_path="/Users/x/Library/LaunchAgents/dev.feedbot.feedbot.plist",
        )
    )
    monkeypatch.setattr(autostart, "enable", enable)
    monkeypatch.setattr(autostart, "status", enable)  # not called via route
    monkeypatch.setattr(autostart, "disable", MagicMock())

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post(
        "/v1/admin/system/autostart", json={"enabled": True}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["platform"] == "macos-launchd"
    assert body["enabled"] is True
    enable.assert_called()


# ── /telemetry ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telemetry_get_default_off(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/system/telemetry")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}


@pytest.mark.asyncio
async def test_telemetry_post_persists_and_audits(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post(
        "/v1/admin/system/telemetry", json={"enabled": True}
    )
    assert resp.status_code == 200
    assert resp.json() == {"enabled": True}

    # GET reflects the persisted value.
    resp2 = await client.get("/v1/admin/system/telemetry")
    assert resp2.json() == {"enabled": True}

    # An audit row landed.
    from feedbot_core.models import AuditEvent
    from sqlalchemy import select

    rows = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.event == "admin.config.changed")
        )
    ).scalars().all()
    assert any(
        '"section":"telemetry"' in (r.details or "") for r in rows
    )
