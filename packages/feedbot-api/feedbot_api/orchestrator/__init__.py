"""Orchestrator — host-mutating operations triggered from the dashboard.

This is the **new component** that was not in the pre-installer API.
It exists so the SPA's Settings page can configure SMTP, the
Telegram bot, the proxy domain, autostart, etc. *without the
operator ever editing files by hand*.

Architecture
------------

Every mutation goes through five steps:

    1. **Validate** the new value at the router layer (regex, type,
       allowed range).
    2. **Persist** to the ``instance_config`` table inside the
       request transaction. Fernet-encrypt secrets at this boundary.
    3. **Project** the new singleton row to side effects:
         - Rewrite ``.env`` atomically (env.regenerate).
         - Restart only the affected services (compose.restart).
         - For domain changes: load a new Caddy config (caddy.apply_domain).
         - For autostart: write the systemd unit / launchd plist.
    4. **Audit** the change with secrets redacted.
    5. **Roll back** the DB write if step 3 fails so the UI never
       sees "saved" without the host actually applying it.

Submodules:

- ``settings``   — typed read-side view of ``instance_config``
- ``env``        — atomic ``.env`` rewrite from settings
- ``compose``    — ``docker compose`` operations
- ``caddy``      — Caddy Admin API client
- ``autostart``  — systemd / launchd unit writers
- ``audit``      — ``admin.config.changed`` + system events

The ``Orchestrator`` facade composes them in the request-time order
and exposes the small surface that I5–I8 routers actually call.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from feedbot_core.llm.crypto import encrypt_key
from feedbot_core.repos import update_instance_config
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.orchestrator import audit, autostart, caddy, compose, env, settings
from feedbot_api.orchestrator.settings import InstanceSettings

log = logging.getLogger("feedbot.orchestrator")


def is_self_host() -> bool:
    """Whether orchestrator routes are exposed.

    Cloud builds set ``FEEDBOT_DEPLOYMENT=cloud`` to short-circuit
    every ``/v1/admin/*`` endpoint at the dependency layer — the
    orchestrator is meaningless in a managed deployment because
    operators don't have file/socket access.
    """
    return (os.getenv("FEEDBOT_DEPLOYMENT") or "self-host").lower() != "cloud"


@dataclass(frozen=True, slots=True)
class _Actor:
    """Who triggered the mutation, for audit purposes."""

    user_id: int | None
    tenant_id: int | None = None
    ip: str | None = None
    user_agent: str | None = None


class Orchestrator:
    """Composition root for host-mutating operations.

    Routers construct one of these per request and call the high-
    level methods (``apply_email``, ``apply_bot``, ``apply_proxy``,
    ``set_autostart``, ``restart_service``). Every method is
    idempotent at the DB layer and best-effort at the host layer.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        user_id: int | None = None,
        tenant_id: int | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ):
        self._session = session
        self._actor = _Actor(
            user_id=user_id,
            tenant_id=tenant_id,
            ip=ip,
            user_agent=user_agent,
        )

    # ── Read ────────────────────────────────────────────────────────

    async def load(self) -> InstanceSettings:
        return await settings.load(self._session)

    # ── Write paths ─────────────────────────────────────────────────

    async def apply_email(
        self,
        *,
        host: str | None,
        port: int | None,
        user: str | None,
        password: str | None,
        sender: str | None,
    ) -> InstanceSettings:
        """Persist SMTP config, rewrite ``.env``, restart api."""
        fields: dict[str, Any] = {
            "smtp_host": host,
            "smtp_port": port,
            "smtp_user": user,
            "smtp_from": sender,
        }
        if password is not None:
            # Empty string clears the column; otherwise encrypt.
            fields["smtp_password_encrypted"] = (
                encrypt_key(password) if password else None
            )
        await update_instance_config(
            self._session, updated_by=self._actor.user_id, **fields
        )

        new_settings = await settings.load(self._session)
        env.regenerate(new_settings)
        await compose.restart("api")

        await audit.config_changed(
            self._session,
            user_id=self._actor.user_id,
            tenant_id=self._actor.tenant_id,
            section="email",
            fields={
                "smtp_host": host,
                "smtp_port": port,
                "smtp_user": user,
                "smtp_from": sender,
                "smtp_password": "<set>" if password else "<cleared>" if password == "" else "<unchanged>",
            },
            ip=self._actor.ip,
            user_agent=self._actor.user_agent,
        )
        return new_settings

    async def apply_bot(
        self, *, token: str | None, username: str | None
    ) -> InstanceSettings:
        """Persist Telegram bot creds, rewrite ``.env``, start bot service."""
        fields: dict[str, Any] = {"telegram_bot_username": username}
        if token is not None:
            fields["telegram_bot_token_encrypted"] = (
                encrypt_key(token) if token else None
            )
        await update_instance_config(
            self._session, updated_by=self._actor.user_id, **fields
        )

        new_settings = await settings.load(self._session)
        env.regenerate(new_settings)

        # Configured → make sure the bot service is up; cleared →
        # stop it. We avoid restart() on a service that may not be
        # running yet (compose returns non-zero on stop-of-stopped).
        if new_settings.bot.is_configured:
            await compose.up("bot", profiles=["bot"])
            await compose.restart("bot")
        else:
            try:
                await compose.stop("bot")
            except compose.ComposeError as exc:
                log.info("bot stop ignored (likely not running): %s", exc)

        await audit.config_changed(
            self._session,
            user_id=self._actor.user_id,
            tenant_id=self._actor.tenant_id,
            section="bot",
            fields={
                "telegram_bot_username": username,
                "telegram_bot_token": "<set>" if token else "<cleared>" if token == "" else "<unchanged>",
            },
            ip=self._actor.ip,
            user_agent=self._actor.user_agent,
        )
        return new_settings

    async def clear_bot(self) -> InstanceSettings:
        """Stop bot service and clear stored credentials."""
        await update_instance_config(
            self._session,
            updated_by=self._actor.user_id,
            telegram_bot_token_encrypted=None,
            telegram_bot_username=None,
        )
        new_settings = await settings.load(self._session)
        env.regenerate(new_settings)
        try:
            await compose.stop("bot")
        except compose.ComposeError as exc:
            log.info("bot stop ignored: %s", exc)

        await audit.config_changed(
            self._session,
            user_id=self._actor.user_id,
            tenant_id=self._actor.tenant_id,
            section="bot",
            fields={"telegram_bot_token": "<cleared>", "telegram_bot_username": None},
            ip=self._actor.ip,
            user_agent=self._actor.user_agent,
        )
        return new_settings

    async def apply_proxy(
        self, *, domain: str, letsencrypt_email: str
    ) -> InstanceSettings:
        """Set domain + LE email, push a new Caddy config."""
        await update_instance_config(
            self._session,
            updated_by=self._actor.user_id,
            domain=domain,
            letsencrypt_email=letsencrypt_email,
            https_enabled=True,
        )
        new_settings = await settings.load(self._session)

        ok = True
        error: str | None = None
        try:
            await caddy.apply_domain(
                domain=domain, letsencrypt_email=letsencrypt_email
            )
        except caddy.CaddyError as exc:
            ok = False
            error = str(exc)
            log.error("caddy apply_domain failed: %s", exc)

        await audit.system_action(
            self._session,
            user_id=self._actor.user_id,
            tenant_id=self._actor.tenant_id,
            action="proxy.apply",
            target=domain,
            ok=ok,
            error=error,
            ip=self._actor.ip,
            user_agent=self._actor.user_agent,
        )
        if not ok:
            raise caddy.CaddyError(error or "caddy reload failed")
        return new_settings

    async def clear_proxy(self) -> InstanceSettings:
        """Remove domain, fall back to IP-only Caddy config."""
        await update_instance_config(
            self._session,
            updated_by=self._actor.user_id,
            domain=None,
            letsencrypt_email=None,
            https_enabled=False,
        )
        new_settings = await settings.load(self._session)

        ok = True
        error: str | None = None
        try:
            await caddy.clear_domain()
        except caddy.CaddyError as exc:
            ok = False
            error = str(exc)
            log.error("caddy clear_domain failed: %s", exc)

        await audit.system_action(
            self._session,
            user_id=self._actor.user_id,
            tenant_id=self._actor.tenant_id,
            action="proxy.clear",
            ok=ok,
            error=error,
            ip=self._actor.ip,
            user_agent=self._actor.user_agent,
        )
        if not ok:
            raise caddy.CaddyError(error or "caddy reload failed")
        return new_settings

    async def proxy_status(self) -> dict[str, Any]:
        """Read-only view of cert provisioning state."""
        s = await settings.load(self._session)
        if not s.proxy.domain:
            return {"domain": None, "configured": False, "https_enabled": False}
        try:
            info = await caddy.cert_status(s.proxy.domain)
        except caddy.CaddyError as exc:
            return {
                "domain": s.proxy.domain,
                "configured": False,
                "https_enabled": s.proxy.https_enabled,
                "error": str(exc),
            }
        return {
            **info,
            "https_enabled": s.proxy.https_enabled,
        }

    # ── Autostart ──────────────────────────────────────────────────

    async def set_autostart(self, *, enabled: bool) -> autostart.AutostartStatus:
        """Toggle systemd / launchd unit + DB flag."""
        await update_instance_config(
            self._session,
            updated_by=self._actor.user_id,
            autostart_enabled=enabled,
        )
        ok = True
        error: str | None = None
        try:
            current = autostart.enable() if enabled else autostart.disable()
        except autostart.AutostartError as exc:
            ok = False
            error = str(exc)
            current = autostart.status()

        await audit.system_action(
            self._session,
            user_id=self._actor.user_id,
            tenant_id=self._actor.tenant_id,
            action="autostart.enable" if enabled else "autostart.disable",
            target=current.platform.value,
            ok=ok,
            error=error,
            ip=self._actor.ip,
            user_agent=self._actor.user_agent,
        )
        if not ok:
            raise autostart.AutostartError(error or "autostart toggle failed")
        return current

    def autostart_status(self) -> autostart.AutostartStatus:
        return autostart.status()

    # ── System actions ─────────────────────────────────────────────

    async def restart_service(self, service: str | None = None) -> None:
        ok = True
        error: str | None = None
        try:
            await compose.restart(service)
        except compose.ComposeError as exc:
            ok = False
            error = str(exc)

        await audit.system_action(
            self._session,
            user_id=self._actor.user_id,
            tenant_id=self._actor.tenant_id,
            action="restart",
            target=service or "all",
            ok=ok,
            error=error,
            ip=self._actor.ip,
            user_agent=self._actor.user_agent,
        )
        if not ok:
            raise compose.ComposeError(
                args=["restart", service or ""],
                returncode=1,
                stderr=error or "",
            )

    async def upgrade(self) -> None:
        """Pull latest images + recreate (migrations run on api boot)."""
        ok = True
        error: str | None = None
        try:
            await compose.pull()
            await compose.up()
        except compose.ComposeError as exc:
            ok = False
            error = str(exc)

        await audit.system_action(
            self._session,
            user_id=self._actor.user_id,
            tenant_id=self._actor.tenant_id,
            action="upgrade",
            ok=ok,
            error=error,
            ip=self._actor.ip,
            user_agent=self._actor.user_agent,
        )
        if not ok:
            raise compose.ComposeError(
                args=["upgrade"], returncode=1, stderr=error or ""
            )


__all__ = [
    "Orchestrator",
    "is_self_host",
    "audit",
    "autostart",
    "caddy",
    "compose",
    "env",
    "settings",
]
