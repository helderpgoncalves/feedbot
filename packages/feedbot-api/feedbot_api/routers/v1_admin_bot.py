"""Admin → Telegram bot endpoints.

Owner-only, self-host only. Each handler delegates to the
orchestrator so the DB row, ``.env`` file, and ``bot`` compose
profile (start / stop) stay in lockstep — see
``feedbot_api/orchestrator/__init__.py``.

Security boundaries:

1. **The encrypted token never leaves the server.** ``BotConfigOut``
   exposes only ``has_token`` + the public username. Plaintext only
   crosses the wire on the inbound side (``POST /config`` body).

2. **Tri-state ``token``.** ``None`` keeps, ``""`` clears, otherwise
   set / rotate. Mirrors the SMTP password and LLM-key patterns.

3. **Test before save.** ``POST /test`` accepts an optional
   ``token`` override so the SPA can validate a freshly-pasted
   value *without* persisting; if omitted, we test what's stored.
   Either way the test never writes to the DB or audits — failing
   tests are a debugging signal, not a mutation.

4. **Cloud short-circuit** via ``require_self_host``: cloud builds
   404 the whole surface so we don't disclose orchestrator
   features.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, Request, status
from feedbot_core.models import User
from feedbot_core.repos import list_chat_links_for_tenant
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import client_ip, client_user_agent
from feedbot_api.deps import get_session, require_owner, require_self_host
from feedbot_api.orchestrator import Orchestrator, settings as orch_settings
from feedbot_api.schemas import (
    BotChatOut,
    BotConfigIn,
    BotConfigOut,
    BotProfileOut,
    BotTestIn,
    BotTestOut,
)

log = logging.getLogger("feedbot.v1.admin.bot")

# Truncation cap for any error string that lands in a response body.
# Telegram rarely echoes credentials but we mirror the SMTP cap so
# the surface is uniform.
_MAX_ERROR_LEN = 240


router = APIRouter(
    prefix="/v1/admin/bot",
    tags=["v1.admin"],
    dependencies=[Depends(require_self_host)],
)


def _truncate(text: str | None) -> str | None:
    if text is None:
        return None
    if len(text) <= _MAX_ERROR_LEN:
        return text
    return text[: _MAX_ERROR_LEN - 1] + "…"


def _normalize_username(username: str | None) -> str | None:
    """Strip leading ``@`` and surrounding whitespace.

    BotFather hands users names like ``@feedbot_acme_bot``; the deep
    link template wants the bare ``feedbot_acme_bot``. Forgive the
    pasted ``@`` so the dashboard isn't a pedant.
    """
    if username is None:
        return None
    cleaned = username.strip().lstrip("@")
    return cleaned or None


def _to_out(s: orch_settings.InstanceSettings) -> BotConfigOut:
    return BotConfigOut(
        username=s.bot.username,
        has_token=s.bot.token is not None,
        configured=s.bot.is_configured,
    )


async def _telegram_get_me(token: str) -> tuple[bool, BotProfileOut | None, str | None]:
    """Round-trip ``GET /bot<token>/getMe``.

    Returns a (ok, profile, error) triple. Errors are truncated to
    ``_MAX_ERROR_LEN``. We never log the token; the URL is
    constructed inline and not stored or echoed in logs.
    """
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        return False, None, _truncate(f"network error: {exc}")

    try:
        body = resp.json() or {}
    except ValueError:
        return False, None, _truncate(f"invalid Telegram response (HTTP {resp.status_code})")

    if not body.get("ok") or resp.status_code >= 300:
        msg = body.get("description") or f"HTTP {resp.status_code}"
        return False, None, _truncate(str(msg))

    result = body.get("result") or {}
    profile = BotProfileOut(
        id=int(result.get("id") or 0),
        username=result.get("username"),
        first_name=result.get("first_name"),
        can_join_groups=result.get("can_join_groups"),
        can_read_all_group_messages=result.get("can_read_all_group_messages"),
    )
    return True, profile, None


@router.get(
    "/config",
    response_model=BotConfigOut,
    summary="Read bot config (owner only). The token is never returned.",
)
async def get_config(
    _me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> BotConfigOut:
    s = await orch_settings.load(session)
    return _to_out(s)


@router.post(
    "/config",
    response_model=BotConfigOut,
    summary="Update bot config + start the bot service (owner only).",
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "description": "DB write succeeded but the bot service failed to start."
        },
    },
)
async def post_config(
    body: BotConfigIn,
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> BotConfigOut:
    orch = Orchestrator(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    s = await orch.apply_bot(
        token=body.token,
        username=_normalize_username(body.username),
    )
    return _to_out(s)


@router.delete(
    "/config",
    response_model=BotConfigOut,
    summary="Stop the bot service and clear stored credentials (owner only).",
)
async def delete_config(
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> BotConfigOut:
    orch = Orchestrator(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    s = await orch.clear_bot()
    return _to_out(s)


@router.post(
    "/test",
    response_model=BotTestOut,
    summary="Validate a Telegram bot token via getMe (owner only).",
)
async def post_test(
    body: BotTestIn,
    _me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> BotTestOut:
    """Round-trip ``getMe`` against a fresh or stored token.

    Always returns 200 with a structured outcome — UI renders the
    raw error on failure. No persistence: this is a "did the user
    paste a working token?" probe, not a settings mutation.
    """
    if body.token:
        token = body.token.strip()
    else:
        s = await orch_settings.load(session)
        if not s.bot.token:
            return BotTestOut(ok=False, error="No token stored — paste one to test.")
        token = s.bot.token

    ok, profile, error = await _telegram_get_me(token)
    if not ok:
        return BotTestOut(ok=False, error=error)
    return BotTestOut(ok=True, profile=profile)


@router.get(
    "/chats",
    response_model=list[BotChatOut],
    summary="List every chat linked across the tenant's projects (owner only).",
)
async def list_chats(
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[BotChatOut]:
    rows = await list_chat_links_for_tenant(session, me.tenant_id)
    return [
        BotChatOut(
            id=link.id,
            platform=link.platform,
            chat_id=link.chat_id,
            title=link.title,
            project_slug=project.slug,
            project_name=project.name,
            created_at=link.created_at,
        )
        for link, project in rows
    ]
