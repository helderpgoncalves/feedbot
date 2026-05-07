"""Structured audit log.

Use ``log_event`` for every sensitive action. Compliance-friendly from day
one (events keep ``ip``, ``user_agent``, and a JSON ``details`` blob); cloud
will surface this on a Security page and ship to an external sink later.

Conventions:

- Event names are dotted, lowercase, present-tense imperative or past-tense
  observation: ``login.ok``, ``login.cross_device``, ``session.revoked``,
  ``api_key.created``, ``api_key.revoked``, ``invite.accepted``,
  ``llm_settings.updated``, ``project.created``.
- ``details`` is small (under ~1KB). Don't dump request bodies; record IDs
  and the diff that matters.
- Failure events end in ``.fail`` (``login.fail``); successes are unsuffixed
  (``login.ok``).
- Never log secrets, magic-link tokens, API keys, or LLM keys.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_core.models import AuditEvent

log = logging.getLogger("feedbot.audit")


async def log_event(
    session: AsyncSession,
    *,
    event: str,
    tenant_id: int | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one audit row. Never raises — audit failure must not break the request."""
    serialized: str | None = None
    if details:
        try:
            serialized = json.dumps(details, default=str, separators=(",", ":"))
            if len(serialized) > 4096:
                serialized = json.dumps(
                    {"_truncated": True, "size": len(serialized)},
                    separators=(",", ":"),
                )
        except (TypeError, ValueError) as exc:
            log.warning("audit details not JSON-serializable: %s", exc)
            serialized = None

    row = AuditEvent(
        event=event,
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        ip=(ip or None),
        user_agent=(user_agent or None),
        details=serialized,
    )
    session.add(row)
    try:
        await session.flush()
    except Exception:  # pragma: no cover — defensive only
        log.exception("audit_log flush failed for event=%s", event)
    # Mirror to structured logs so devops sees it without a DB query.
    log.info(
        "audit event=%s tenant_id=%s user_id=%s project_id=%s",
        event,
        tenant_id,
        user_id,
        project_id,
    )
    return row
