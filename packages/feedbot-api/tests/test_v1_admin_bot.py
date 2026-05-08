"""HTTP tests for ``/v1/admin/bot/*``.

Same shape as ``test_v1_admin_email.py``: focus on the wire
contract (auth, redaction, tri-state, cloud short-circuit) and
mock anything that would shell out / hit the network.

The Telegram ``getMe`` round trip is exercised via a fake
``httpx.AsyncClient`` so we never touch ``api.telegram.org``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from feedbot_core.llm.crypto import encrypt_key
from feedbot_core.models import ChatLink, Role
from feedbot_core.repos import update_instance_config


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def stub_orchestrator_side_effects(monkeypatch, tmp_path: Path):
    """Neutralise host-side calls inside Orchestrator.apply_bot / clear_bot."""
    from feedbot_api.orchestrator import compose

    monkeypatch.setenv("FEEDBOT_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setattr(compose, "up", AsyncMock())
    monkeypatch.setattr(compose, "restart", AsyncMock())
    monkeypatch.setattr(compose, "stop", AsyncMock())
    yield


class _FakeTelegramResponse:
    """Stand-in for httpx.Response used inside the bot router's _telegram_get_me."""

    def __init__(self, *, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Records the URL hit and returns a queued response."""

    def __init__(self, *, response: _FakeTelegramResponse | None = None, raise_exc: Exception | None = None):
        self._response = response
        self._raise = raise_exc
        self.urls: list[str] = []

    def __init__as_factory(self, *args, **kwargs):  # pragma: no cover
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, *args, **kwargs):
        self.urls.append(url)
        if self._raise is not None:
            raise self._raise
        assert self._response is not None
        return self._response


@pytest.fixture
def fake_telegram(monkeypatch):
    """Replace httpx.AsyncClient inside the bot router with a controllable fake.

    Returns a callable: ``set_response(payload, status=200)`` or
    ``set_error(exc)`` to configure what the next ``getMe`` round
    trip sees. The most-recent fake's ``urls`` list is the call log.
    """
    state: dict = {"client": None}

    def factory(**_kwargs):
        # Fall back to a default 200-with-empty-result so a forgotten
        # configure call doesn't make tests hang.
        c = state["client"] or _FakeAsyncClient(
            response=_FakeTelegramResponse(payload={"ok": True, "result": {}})
        )
        state["client"] = c
        return c

    import feedbot_api.routers.v1_admin_bot as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", factory)

    def set_response(payload: dict, *, status: int = 200) -> _FakeAsyncClient:
        c = _FakeAsyncClient(response=_FakeTelegramResponse(status_code=status, payload=payload))
        state["client"] = c
        return c

    def set_error(exc: Exception) -> _FakeAsyncClient:
        c = _FakeAsyncClient(raise_exc=exc)
        state["client"] = c
        return c

    return type("FakeTelegram", (), {"set_response": staticmethod(set_response), "set_error": staticmethod(set_error)})


# ── auth ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config_requires_login(client):
    resp = await client.get("/v1/admin/bot/config")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_config_admin_forbidden(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await login_as(admin)

    resp = await client.get("/v1/admin/bot/config")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cloud_deployment_returns_404(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    monkeypatch.setenv("FEEDBOT_DEPLOYMENT", "cloud")
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/bot/config")
    assert resp.status_code == 404


# ── GET /config never returns the token ─────────────────────────────


@pytest.mark.asyncio
async def test_get_config_redacts_token(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    await update_instance_config(
        db_session,
        telegram_bot_token_encrypted=encrypt_key("123:supersecrettoken"),
        telegram_bot_username="feedbot_acme_bot",
    )
    await db_session.commit()

    resp = await client.get("/v1/admin/bot/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "username": "feedbot_acme_bot",
        "has_token": True,
        "configured": True,
    }
    assert "supersecret" not in resp.text


# ── POST /config tri-state + username normalisation ────────────────


@pytest.mark.asyncio
async def test_post_config_strips_at_from_username(
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
        "/v1/admin/bot/config",
        json={"token": "123:abc", "username": "@feedbot_acme_bot"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == "feedbot_acme_bot"
    assert body["has_token"] is True
    assert body["configured"] is True


@pytest.mark.asyncio
async def test_post_config_keep_token_with_none(
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
        telegram_bot_token_encrypted=encrypt_key("old:token"),
        telegram_bot_username="oldbot",
    )
    await db_session.commit()

    # Update only the username; token must survive.
    resp = await client.post(
        "/v1/admin/bot/config",
        json={"username": "newbot"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "newbot"
    assert resp.json()["has_token"] is True


# ── DELETE /config ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_config_clears_creds(
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
        telegram_bot_token_encrypted=encrypt_key("tok"),
        telegram_bot_username="bot",
    )
    await db_session.commit()

    resp = await client.delete("/v1/admin/bot/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "username": None,
        "has_token": False,
        "configured": False,
    }


# ── POST /test ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_returns_error_when_no_token(
    client, db_session, make_tenant, make_user, login_as, fake_telegram
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post("/v1/admin/bot/test", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "no token" in (body["error"] or "").lower()


@pytest.mark.asyncio
async def test_test_uses_inline_token_without_persistence(
    client,
    db_session,
    make_tenant,
    make_user,
    login_as,
    fake_telegram,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    fake = fake_telegram.set_response(
        {
            "ok": True,
            "result": {
                "id": 42,
                "username": "feedbot_acme_bot",
                "first_name": "Feedbot",
                "can_join_groups": True,
                "can_read_all_group_messages": False,
            },
        }
    )

    resp = await client.post(
        "/v1/admin/bot/test", json={"token": "999:fresh-from-botfather"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["profile"] == {
        "id": 42,
        "username": "feedbot_acme_bot",
        "first_name": "Feedbot",
        "can_join_groups": True,
        "can_read_all_group_messages": False,
    }
    # Token reached the URL — confirm we hit Telegram, not random.
    assert fake.urls and fake.urls[0].endswith("/bot999:fresh-from-botfather/getMe")
    # Nothing was persisted (the inline-token path skips the DB).
    from feedbot_core.repos import get_instance_config

    cfg = await get_instance_config(db_session)
    assert cfg.telegram_bot_token_encrypted is None


@pytest.mark.asyncio
async def test_test_returns_telegram_error(
    client,
    db_session,
    make_tenant,
    make_user,
    login_as,
    fake_telegram,
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    fake_telegram.set_response(
        {"ok": False, "description": "Unauthorized"}, status=401
    )

    resp = await client.post(
        "/v1/admin/bot/test", json={"token": "bad:token"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "unauthorized" in (body["error"] or "").lower()


@pytest.mark.asyncio
async def test_test_handles_network_error(
    client,
    db_session,
    make_tenant,
    make_user,
    login_as,
    fake_telegram,
):
    import httpx

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    fake_telegram.set_error(httpx.ConnectError("dns failure"))

    resp = await client.post(
        "/v1/admin/bot/test", json={"token": "any:thing"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "network" in (body["error"] or "").lower()


# ── GET /chats ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_chats_returns_only_this_tenant(
    client,
    db_session,
    make_tenant,
    make_user,
    make_project,
    login_as,
):
    tenant = await make_tenant(name="Acme")
    other = await make_tenant(name="Other Co")
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    p = await make_project(tenant=tenant, slug="demo", name="Demo")
    p_other = await make_project(tenant=other, slug="demo2", name="Demo 2")

    db_session.add_all(
        [
            ChatLink(project_id=p.id, platform="telegram", chat_id="-100", title="Acme Eng"),
            ChatLink(project_id=p_other.id, platform="telegram", chat_id="-200", title="Other"),
        ]
    )
    await db_session.commit()

    resp = await client.get("/v1/admin/bot/chats")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["chat_id"] == "-100"
    assert rows[0]["project_slug"] == "demo"
