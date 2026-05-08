"""Admin → Email delivery (SMTP) endpoints.

Owner-only, self-host only. Each handler delegates to the orchestrator
so the DB row, ``.env`` file, and ``api`` container restart stay in
lockstep — see ``feedbot_api/orchestrator/__init__.py`` for the
"validate → persist → project → restart → audit" pipeline.

Security boundaries:

1. **The encrypted password never leaves the server.** ``EmailConfigOut``
   exposes only ``has_password`` and the non-secret fields. The wire
   protocol gives no way to retrieve the plaintext.

2. **Tri-state ``password``.** Mirrors the LLM-settings pattern: ``None``
   keeps the stored value, ``""`` clears it, any other string rotates.

3. **Test endpoint never persists.** ``POST /test`` does an ad-hoc SMTP
   send with the *currently stored* (or just-submitted, via "Test before
   save") credentials and returns a structured outcome. Errors are
   truncated to 240 chars before they hit storage or the wire.

4. **Cloud short-circuit.** The shared ``require_self_host`` dep returns
   404 on cloud builds so the route surface looks identical to "not
   implemented" rather than "forbidden" — no information disclosure.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status
from feedbot_core.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import client_ip, client_user_agent
from feedbot_api.deps import get_session, require_owner, require_self_host
from feedbot_api.email_backend import SMTPBackend
from feedbot_api.orchestrator import Orchestrator
from feedbot_api.orchestrator import settings as orch_settings
from feedbot_api.schemas import (
    EmailConfigIn,
    EmailConfigOut,
    EmailTestIn,
    EmailTestOut,
)

log = logging.getLogger("feedbot.v1.admin.email")

# Cap any SMTP / connection error at this length before it lands in the
# response body or the audit row. SMTP servers sometimes echo the
# username in error responses; the cap keeps that out of audit storage.
_MAX_ERROR_LEN = 240


router = APIRouter(
    prefix="/v1/admin/email",
    tags=["v1.admin"],
    dependencies=[Depends(require_self_host)],
)


def _truncate(text: str | None) -> str | None:
    if text is None:
        return None
    if len(text) <= _MAX_ERROR_LEN:
        return text
    return text[: _MAX_ERROR_LEN - 1] + "…"


def _to_out(s: orch_settings.InstanceSettings) -> EmailConfigOut:
    return EmailConfigOut(
        host=s.smtp.host,
        port=s.smtp.port,
        user=s.smtp.user,
        sender=s.smtp.sender,
        has_password=s.smtp.password is not None,
        configured=s.smtp.is_configured,
    )


@router.get(
    "/config",
    response_model=EmailConfigOut,
    summary="Read SMTP config (owner only). The password is never returned.",
)
async def get_config(
    _me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> EmailConfigOut:
    s = await orch_settings.load(session)
    return _to_out(s)


@router.post(
    "/config",
    response_model=EmailConfigOut,
    summary="Update SMTP config + restart api (owner only).",
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "description": "DB write succeeded but the api restart failed."
        },
    },
)
async def post_config(
    body: EmailConfigIn,
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> EmailConfigOut:
    orch = Orchestrator(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    s = await orch.apply_email(
        host=body.host,
        port=body.port,
        user=body.user,
        # ``apply_email`` already implements tri-state on the password
        # column: None = keep, "" = clear, "..." = encrypt + set.
        password=body.password,
        sender=body.sender,
    )
    return _to_out(s)


@router.post(
    "/test",
    response_model=EmailTestOut,
    summary="Send a test email using the stored SMTP creds (owner only).",
)
async def post_test(
    body: EmailTestIn,
    _me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> EmailTestOut:
    """Round-trip a fixed message through the configured SMTP server.

    Always returns 200 with a structured outcome — UI renders the raw
    error on failure. We never persist the result, only the audit row
    that ``apply_email`` already writes on save; a failed test is the
    operator's debugging signal, not an audit-worthy mutation.
    """
    s = await orch_settings.load(session)
    if not s.smtp.is_configured or s.smtp.password is None:
        return EmailTestOut(ok=False, error="SMTP is not configured")

    try:
        backend = SMTPBackend(
            host=s.smtp.host or "",
            port=s.smtp.port or 587,
            username=s.smtp.user or "",
            password=s.smtp.password,
            sender=s.smtp.sender or "",
            starttls=(s.smtp.port or 587) != 465,
        )
        backend.send(
            to=body.to,
            subject="Feedbot SMTP test",
            body=(
                "This is a test email from your Feedbot instance.\n\n"
                "If you received this message, magic-link login and "
                "invitation emails will work for your users."
            ),
        )
    except Exception as exc:
        log.warning("orchestrator email-test failed: %s", exc)
        return EmailTestOut(ok=False, error=_truncate(str(exc)))

    return EmailTestOut(ok=True)
