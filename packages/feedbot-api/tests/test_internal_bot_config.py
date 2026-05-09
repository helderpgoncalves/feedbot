"""Tests for ``GET /v1/internal/bot-config``.

Wire contract the bot service depends on:
  - Empty DB → ``token: null`` (the bot polls and waits).
  - Token saved in InstanceConfig → returns the *decrypted* token.
  - Auth required: missing/wrong bot token → 401.
"""

from __future__ import annotations

import pytest
from feedbot_core.llm.crypto import encrypt_key
from feedbot_core.repos import update_instance_config


@pytest.mark.asyncio
async def test_bot_config_empty_when_unconfigured(client):
    resp = await client.get(
        "/v1/internal/bot-config",
        headers={"Authorization": "Bearer test-bot-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"token": None, "username": None}


@pytest.mark.asyncio
async def test_bot_config_returns_decrypted_token(client, db_session):
    await update_instance_config(
        db_session,
        telegram_bot_token_encrypted=encrypt_key("123:secret-token"),
        telegram_bot_username="feedbot_acme_bot",
    )
    await db_session.commit()

    resp = await client.get(
        "/v1/internal/bot-config",
        headers={"Authorization": "Bearer test-bot-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "token": "123:secret-token",
        "username": "feedbot_acme_bot",
    }


@pytest.mark.asyncio
async def test_bot_config_requires_bot_token(client):
    resp = await client.get("/v1/internal/bot-config")
    assert resp.status_code == 401

    resp = await client.get(
        "/v1/internal/bot-config",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401
