"""Audit wrapper for orchestrator mutations.

Every action that changes ``instance_config``, the ``.env`` file,
the Caddy config, or the autostart unit emits an
``admin.config.changed`` event. We never log secrets — only the
diff'd field names and any non-secret metadata (e.g. domain, smtp
host, autostart enabled flag).

The shared ``feedbot_core.audit.log_event`` does the row insert and
mirrors to structured logs; this wrapper exists so the orchestrator
has a single place to enforce the event-name discipline and the
"never serialize secrets" rule.
"""

from __future__ import annotations

from typing import Any

from feedbot_core.audit import log_event
from sqlalchemy.ext.asyncio import AsyncSession

# Field names whose values are secret — tracking the *fact that they
# changed* is fine, but the value itself never enters the audit row.
_SECRET_FIELDS: frozenset[str] = frozenset(
    {
        "smtp_password",
        "smtp_password_encrypted",
        "telegram_bot_token",
        "telegram_bot_token_encrypted",
    }
)


def redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Replace secret values with ``"<redacted>"``."""
    return {
        k: ("<redacted>" if k in _SECRET_FIELDS else v)
        for k, v in fields.items()
    }


async def config_changed(
    session: AsyncSession,
    *,
    user_id: int | None,
    tenant_id: int | None = None,
    section: str,
    fields: dict[str, Any],
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Emit ``admin.config.changed`` for an orchestrator mutation.

    ``section`` is the high-level area the change touches
    (``email``, ``bot``, ``proxy``, ``autostart``, ``telemetry``,
    ``system``). ``fields`` lists the keys that were updated; secret
    values are redacted before serialization.
    """
    details = {
        "section": section,
        "changed": sorted(fields.keys()),
        "values": redact(fields),
    }
    await log_event(
        session,
        event="admin.config.changed",
        user_id=user_id,
        tenant_id=tenant_id,
        ip=ip,
        user_agent=user_agent,
        details=details,
    )


async def system_action(
    session: AsyncSession,
    *,
    user_id: int | None,
    tenant_id: int | None = None,
    action: str,
    target: str | None = None,
    ok: bool = True,
    error: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Emit a system-level event (restart, upgrade, autostart toggle).

    ``action`` is one of ``restart``, ``upgrade``, ``autostart.enable``,
    ``autostart.disable``, ``proxy.apply``, ``proxy.clear``. The
    suffix follows the audit convention: successes are unsuffixed,
    failures get ``.fail``.
    """
    event = f"admin.system.{action}" + ("" if ok else ".fail")
    details: dict[str, Any] = {"action": action}
    if target is not None:
        details["target"] = target
    if error is not None:
        details["error"] = error
    await log_event(
        session,
        event=event,
        user_id=user_id,
        tenant_id=tenant_id,
        ip=ip,
        user_agent=user_agent,
        details=details,
    )
