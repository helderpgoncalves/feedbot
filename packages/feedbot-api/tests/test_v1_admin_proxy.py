"""HTTP tests for ``/v1/admin/proxy/*``.

Same shape as the email + bot tests. The Caddy admin API is
mocked at the orchestrator submodule so we never try to reach
``http://caddy:2019``; ``socket.getaddrinfo`` is monkeypatched
for the DNS pre-flight to keep tests offline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from feedbot_core.models import Role
from feedbot_core.repos import update_instance_config


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def stub_caddy(monkeypatch):
    """Replace caddy.apply_domain / clear_domain / cert_status."""
    from feedbot_api.orchestrator import caddy

    apply_mock = AsyncMock()
    clear_mock = AsyncMock()
    status_mock = AsyncMock(
        return_value={"domain": None, "configured": False, "policy_count": 0}
    )
    monkeypatch.setattr(caddy, "apply_domain", apply_mock)
    monkeypatch.setattr(caddy, "clear_domain", clear_mock)
    monkeypatch.setattr(caddy, "cert_status", status_mock)
    return type(
        "CaddyMocks",
        (),
        {"apply": apply_mock, "clear": clear_mock, "status": status_mock},
    )


# ── auth ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config_requires_login(client):
    resp = await client.get("/v1/admin/proxy/config")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_config_admin_forbidden(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await login_as(admin)

    resp = await client.get("/v1/admin/proxy/config")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cloud_deployment_returns_404(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    monkeypatch.setenv("FEEDBOT_DEPLOYMENT", "cloud")
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/proxy/config")
    assert resp.status_code == 404


# ── GET /config ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config_empty(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/proxy/config")
    assert resp.status_code == 200
    assert resp.json() == {
        "domain": None,
        "letsencrypt_email": None,
        "https_enabled": False,
        "configured": False,
    }


# ── POST /config validation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_config_rejects_url(
    client, db_session, make_tenant, make_user, login_as, stub_caddy
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post(
        "/v1/admin/proxy/config",
        json={
            "domain": "https://feedbot.example.com",  # scheme not allowed
            "letsencrypt_email": "ops@example.com",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_config_rejects_bad_email(
    client, db_session, make_tenant, make_user, login_as, stub_caddy
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post(
        "/v1/admin/proxy/config",
        json={"domain": "feedbot.example.com", "letsencrypt_email": "no-at"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_config_calls_caddy_and_persists(
    client, db_session, make_tenant, make_user, login_as, stub_caddy
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post(
        "/v1/admin/proxy/config",
        json={
            "domain": "Feedbot.Example.com",  # casing normalised
            "letsencrypt_email": "ops@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "domain": "feedbot.example.com",
        "letsencrypt_email": "ops@example.com",
        "https_enabled": True,
        "configured": True,
    }
    stub_caddy.apply.assert_awaited_once_with(
        domain="feedbot.example.com", letsencrypt_email="ops@example.com"
    )


@pytest.mark.asyncio
async def test_post_config_502_when_caddy_fails(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import caddy

    monkeypatch.setattr(
        caddy,
        "apply_domain",
        AsyncMock(side_effect=caddy.CaddyError("admin API unreachable")),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post(
        "/v1/admin/proxy/config",
        json={
            "domain": "feedbot.example.com",
            "letsencrypt_email": "ops@example.com",
        },
    )
    assert resp.status_code == 502
    assert "caddy" in resp.json().get("detail", "").lower()


# ── DELETE /config ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_config_clears(
    client, db_session, make_tenant, make_user, login_as, stub_caddy
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    await update_instance_config(
        db_session,
        domain="feedbot.example.com",
        letsencrypt_email="ops@example.com",
        https_enabled=True,
    )
    await db_session.commit()

    resp = await client.delete("/v1/admin/proxy/config")
    assert resp.status_code == 200
    assert resp.json()["domain"] is None
    assert resp.json()["https_enabled"] is False
    stub_caddy.clear.assert_awaited_once()


# ── GET /status ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_no_domain_returns_unconfigured(
    client, db_session, make_tenant, make_user, login_as, stub_caddy
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/proxy/status")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
    assert resp.json()["domain"] is None


@pytest.mark.asyncio
async def test_status_surfaces_caddy_error(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    """When the Caddy admin API is down, /status returns 200 with error set."""
    from feedbot_api.orchestrator import caddy

    monkeypatch.setattr(
        caddy,
        "cert_status",
        AsyncMock(side_effect=caddy.CaddyError("connection refused")),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    await update_instance_config(
        db_session,
        domain="feedbot.example.com",
        letsencrypt_email="ops@example.com",
        https_enabled=True,
    )
    await db_session.commit()

    resp = await client.get("/v1/admin/proxy/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["domain"] == "feedbot.example.com"
    assert body["configured"] is False
    assert "connection refused" in (body["error"] or "")


# ── POST /dns-check ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dns_check_resolves(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    import feedbot_api.routers.v1_admin_proxy as mod

    # Pretend the host's outbound IP is 1.2.3.4 and the domain
    # resolves to two A records, one of which matches.
    monkeypatch.setattr(mod, "_resolve_server_ip", lambda: "1.2.3.4")
    monkeypatch.setattr(
        mod.socket,
        "getaddrinfo",
        lambda host, port: [
            (mod.socket.AF_INET, 0, 0, "", ("1.2.3.4", 0)),
            (mod.socket.AF_INET, 0, 0, "", ("5.6.7.8", 0)),
        ],
    )

    resp = await client.post(
        "/v1/admin/proxy/dns-check",
        json={"domain": "feedbot.example.com"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["domain"] == "feedbot.example.com"
    assert sorted(body["resolved_ips"]) == ["1.2.3.4", "5.6.7.8"]
    assert body["server_ip"] == "1.2.3.4"
    assert body["matches"] is True
    assert body["error"] is None


@pytest.mark.asyncio
async def test_dns_check_handles_nxdomain(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    import socket as real_socket

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    import feedbot_api.routers.v1_admin_proxy as mod

    monkeypatch.setattr(mod, "_resolve_server_ip", lambda: "1.2.3.4")

    def boom(*_a, **_k):
        raise real_socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr(mod.socket, "getaddrinfo", boom)

    resp = await client.post(
        "/v1/admin/proxy/dns-check",
        json={"domain": "does-not-resolve.example"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_ips"] == []
    assert body["matches"] is False
    assert body["error"] is not None
