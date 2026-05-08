"""Read-side facade over ``instance_config``.

The DB row is the source of truth for every UI-managed knob (SMTP,
Telegram bot, domain, autostart, telemetry). Encrypted columns hold
Fernet ciphertext using the same key derivation as project LLM keys
(``feedbot_core.llm.crypto``); decryption only happens here, at the
boundary, never inside repos or routers.

This module does **not** mutate the row — that goes through
``feedbot_core.repos.update_instance_config`` (or, more usually, via
the orchestrator facade which also rewrites ``.env`` and audits).
"""

from __future__ import annotations

from dataclasses import dataclass

from feedbot_core.llm.crypto import decrypt_key
from feedbot_core.llm.exceptions import LLMConfigError
from feedbot_core.models import InstanceConfig
from feedbot_core.repos import get_instance_config
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str | None
    port: int | None
    user: str | None
    password: str | None  # decrypted; never log
    sender: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.port)


@dataclass(frozen=True, slots=True)
class BotConfig:
    token: str | None  # decrypted; never log
    username: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.username)


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    domain: str | None
    https_enabled: bool
    letsencrypt_email: str | None


@dataclass(frozen=True, slots=True)
class SystemConfig:
    autostart_enabled: bool
    telemetry_enabled: bool


@dataclass(frozen=True, slots=True)
class InstanceSettings:
    """Decrypted, typed view of the singleton row."""

    smtp: SmtpConfig
    bot: BotConfig
    proxy: ProxyConfig
    system: SystemConfig


def _safe_decrypt(blob: bytes | None) -> str | None:
    """Decrypt or return ``None``.

    A row may have ciphertext encrypted under a now-rotated
    ``FEEDBOT_SECRET_KEY``; rather than 500-ing the whole settings
    page, we treat that as "not configured" and let the UI prompt the
    owner to re-enter the secret. The original repo write path still
    surfaces encryption errors loudly when the user changes a value.
    """
    if blob is None:
        return None
    try:
        return decrypt_key(blob)
    except LLMConfigError:
        return None


def from_row(row: InstanceConfig) -> InstanceSettings:
    return InstanceSettings(
        smtp=SmtpConfig(
            host=row.smtp_host,
            port=row.smtp_port,
            user=row.smtp_user,
            password=_safe_decrypt(row.smtp_password_encrypted),
            sender=row.smtp_from,
        ),
        bot=BotConfig(
            token=_safe_decrypt(row.telegram_bot_token_encrypted),
            username=row.telegram_bot_username,
        ),
        proxy=ProxyConfig(
            domain=row.domain,
            https_enabled=row.https_enabled,
            letsencrypt_email=row.letsencrypt_email,
        ),
        system=SystemConfig(
            autostart_enabled=row.autostart_enabled,
            telemetry_enabled=row.telemetry_enabled,
        ),
    )


async def load(session: AsyncSession) -> InstanceSettings:
    """Load + decrypt the singleton row."""
    row = await get_instance_config(session)
    return from_row(row)
