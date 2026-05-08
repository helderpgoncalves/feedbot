"""Tests for the singleton ``instance_config`` table.

Three things to prove:

1. The migration's ``INSERT INTO instance_config (id) VALUES (1)`` has
   run, so ``get_instance_config`` returns a fully-defaulted row on a
   fresh database.
2. ``update_instance_config`` mutates that single row in place and
   never creates a second one — the ``CHECK (id = 1)`` constraint
   would refuse, so we test that updates are upserts not inserts.
3. The Fernet roundtrip (encrypt → write → read → decrypt) works for
   the secret columns (``smtp_password_encrypted``,
   ``telegram_bot_token_encrypted``) using the same crypto module
   M3 introduced for LLM keys.
"""

from __future__ import annotations

import pytest
from feedbot_core.llm.crypto import decrypt_key, encrypt_key
from feedbot_core.models import InstanceConfig
from feedbot_core.repos import get_instance_config, update_instance_config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_migration_inserts_singleton_row(db_session: AsyncSession):
    row = await get_instance_config(db_session)
    assert row.id == 1
    # Defaults from the migration: nothing configured, both toggles off.
    assert row.smtp_host is None
    assert row.smtp_password_encrypted is None
    assert row.telegram_bot_token_encrypted is None
    assert row.domain is None
    assert row.https_enabled is False
    assert row.autostart_enabled is False
    assert row.telemetry_enabled is False


@pytest.mark.asyncio
async def test_update_keeps_one_row(db_session: AsyncSession):
    """Repeated updates must never produce a second row."""
    await update_instance_config(db_session, smtp_host="smtp.example.com")
    await update_instance_config(db_session, telemetry_enabled=True)
    await update_instance_config(db_session, smtp_host="smtp.other.com")

    count = (
        await db_session.execute(select(func.count()).select_from(InstanceConfig))
    ).scalar_one()
    assert count == 1

    row = await get_instance_config(db_session)
    assert row.smtp_host == "smtp.other.com"
    assert row.telemetry_enabled is True


@pytest.mark.asyncio
async def test_update_ignores_unknown_fields(db_session: AsyncSession):
    """Defensive: a stale field name should not raise — routers validate first."""
    await update_instance_config(db_session, totally_made_up_field="x", smtp_host="ok")
    row = await get_instance_config(db_session)
    assert row.smtp_host == "ok"
    assert not hasattr(row, "totally_made_up_field")


@pytest.mark.asyncio
async def test_fernet_roundtrip_on_smtp_password(db_session: AsyncSession):
    plaintext = "super-secret-smtp-password-with-unicode-éç"
    ciphertext = encrypt_key(plaintext)
    assert ciphertext != plaintext.encode()

    await update_instance_config(db_session, smtp_password_encrypted=ciphertext)

    row = await get_instance_config(db_session)
    assert row.smtp_password_encrypted == ciphertext
    assert decrypt_key(row.smtp_password_encrypted) == plaintext


@pytest.mark.asyncio
async def test_fernet_roundtrip_on_telegram_token(db_session: AsyncSession):
    plaintext = "1234567890:AABBccDDee-FFgg_HHiiJJkkLL"
    ciphertext = encrypt_key(plaintext)

    await update_instance_config(db_session, telegram_bot_token_encrypted=ciphertext)

    row = await get_instance_config(db_session)
    assert decrypt_key(row.telegram_bot_token_encrypted) == plaintext


@pytest.mark.asyncio
async def test_updated_by_tracks_user(
    db_session: AsyncSession, make_tenant, make_user
):
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="owner@x.com")

    await update_instance_config(
        db_session, updated_by=owner.id, autostart_enabled=True
    )

    row = await get_instance_config(db_session)
    assert row.updated_by == owner.id
    assert row.autostart_enabled is True
