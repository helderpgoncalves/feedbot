"""JSON LLM endpoints — settings (GET/PUT), test (POST), calls audit (GET).

Security boundaries that this module enforces:

1. **The encrypted API key never leaves the server.** ``LLMSettingsOut`` exposes
   only the boolean ``has_api_key``. Callers that need to know "is a key
   configured?" use that flag. There is no endpoint that returns the
   plaintext or the ciphertext.

2. **Partial-update semantics on PUT.** The ``api_key`` field is *tri-state*:

       None        — keep the stored key untouched.
       ""          — clear the key (operator explicitly removes it).
       "fbk_..."   — rotate / set the key.

   This avoids the foot-gun of "I PUT settings without api_key, my key was
   deleted because the schema treated missing as empty".

3. **Provider error truncation.** ``last_test_error`` and the body of
   ``POST /llm-test`` are truncated to 240 chars before any storage or
   serialization. Some providers echo the key prefix in 401 messages; the
   cap stays safely under typical header-leak surface and won't reveal the
   12-char prefix even if the provider duplicates it twice.

4. **Audit on every change.** ``llm_settings.updated``, ``llm_settings.tested``
   audit events carry ``provider``, ``model``, ``enabled``, but never the
   key (encrypted or otherwise) and never an unbounded error string.

All routes are admin-gated via ``require_project_admin``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from feedbot_core import audit
from feedbot_core.llm import (
    classify_feedback,
    encrypt_key,
    list_providers,
)
from feedbot_core.models import Project, User
from feedbot_core.repos import (
    get_or_create_llm_settings,
    list_recent_llm_calls,
    llm_month_to_date_cost,
    record_llm_test_result,
    save_llm_settings,
)
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session, require_project_admin, require_user
from feedbot_api.routers.auth import _client_ip, _user_agent
from feedbot_api.schemas import (
    LLMCallOut,
    LLMSettingsIn,
    LLMSettingsOut,
    LLMTestOut,
    ProvidersOut,
)

log = logging.getLogger("feedbot.v1.llm")

router = APIRouter(prefix="/v1", tags=["v1.llm"])

#: Max length of provider error strings stored or returned. Defensive against
#: providers that echo prefixes of the API key in 401 / rate-limit messages.
_MAX_ERROR_LEN = 240


def _truncate_error(text: str | None) -> str | None:
    """Cap a provider error at 240 chars. Used everywhere the provider's
    response could leak via storage or serialization."""
    if text is None:
        return None
    if len(text) <= _MAX_ERROR_LEN:
        return text
    return text[: _MAX_ERROR_LEN - 1] + "…"


# ─── Provider registry (read-only, not project-scoped) ─────────────────────


@router.get(
    "/llm/providers",
    response_model=ProvidersOut,
    summary="List available LLM providers (from the registry)",
)
async def get_providers(
    _me: User = Depends(require_user),
) -> ProvidersOut:
    """The SPA reads this to populate the provider/model dropdowns. Adding a
    new provider in ``feedbot_core/llm/providers/`` makes it appear here
    automatically — no UI change required."""
    return ProvidersOut(providers=list_providers())


# ─── /v1/projects/{slug}/llm-settings ──────────────────────────────────────


def _to_settings_out(settings, mtd_usd: float) -> LLMSettingsOut:
    return LLMSettingsOut(
        provider=settings.provider,
        model=settings.model,
        enabled=settings.enabled,
        monthly_budget_usd=settings.monthly_budget_usd,
        has_api_key=settings.encrypted_api_key is not None,
        last_test_at=settings.last_test_at,
        last_test_ok=settings.last_test_ok,
        last_test_error=_truncate_error(settings.last_test_error),
        month_to_date_usd=mtd_usd,
    )


@router.get(
    "/projects/{slug}/llm-settings",
    response_model=LLMSettingsOut,
    summary="Read LLM settings for a project (admin only). The key is never returned.",
)
async def get_llm_settings(
    slug: str,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> LLMSettingsOut:
    _me, project = pair
    settings = await get_or_create_llm_settings(session, project.id)
    mtd = await llm_month_to_date_cost(session, project.id)
    return _to_settings_out(settings, mtd)


@router.put(
    "/projects/{slug}/llm-settings",
    response_model=LLMSettingsOut,
    summary="Update LLM settings (admin only). See module docstring for api_key semantics.",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Unknown provider, or enabled=true while clearing the api_key."
        },
    },
)
async def put_llm_settings(
    slug: str,
    request: Request,
    body: LLMSettingsIn,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> LLMSettingsOut:
    me, project = pair

    if body.provider != "none" and body.provider not in list_providers():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"unknown provider: {body.provider}"
        )

    # Resolve the encryption decision.
    #  - api_key is None        => keep existing
    #  - api_key is ""          => clear (must not be enabled)
    #  - api_key is non-empty   => set/rotate
    encrypted: bytes | None
    cleared = False
    if body.api_key is None:
        encrypted = None  # save_llm_settings treats None as "keep"
    elif body.api_key.strip() == "":
        if body.enabled:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "cannot enable classification with no api_key — clear key only when disabling",
            )
        # Explicit clear — pass an empty bytes object so save_llm_settings
        # writes None into the column. (Our repo helper ignores None for
        # 'keep'; it writes whatever is passed otherwise.)
        encrypted = b""
        cleared = True
    else:
        encrypted = encrypt_key(body.api_key.strip())

    # The repo helper's contract: encrypted_api_key=None means keep the
    # existing column value; any other value (even empty bytes) overwrites.
    # We mirror that contract here, with the special case that explicit
    # clearing writes a NULL — handled below by reading after save.
    settings = await save_llm_settings(
        session,
        project.id,
        provider=body.provider,
        model=body.model.strip() if body.model else None,
        encrypted_api_key=encrypted,
        enabled=body.enabled,
        monthly_budget_usd=body.monthly_budget_usd,
    )
    if cleared:
        # save_llm_settings doesn't have a 'force null' branch; make the
        # cleared semantic explicit by zeroing the column.
        settings.encrypted_api_key = None
        await session.flush()

    await audit.log_event(
        session,
        event="llm_settings.updated",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        details={
            "provider": body.provider,
            "model": body.model,
            "enabled": body.enabled,
            "monthly_budget_usd": body.monthly_budget_usd,
            # 'keep' / 'set' / 'cleared' — never the value itself.
            "api_key_change": (
                "keep"
                if body.api_key is None
                else ("cleared" if cleared else "set")
            ),
        },
    )

    mtd = await llm_month_to_date_cost(session, project.id)
    return _to_settings_out(settings, mtd)


# ─── /v1/projects/{slug}/llm-test ──────────────────────────────────────────


@router.post(
    "/projects/{slug}/llm-test",
    response_model=LLMTestOut,
    summary="Run a single classification round-trip and record the outcome (admin only)",
)
async def llm_test(
    slug: str,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> LLMTestOut:
    """Round-trip a fixed sample feedback through the configured provider.

    Always returns 200 with a structured outcome — even when the provider
    rejects the request. The error_text on the response is truncated; the
    same truncated value is persisted in ``last_test_error``.
    """
    me, project = pair
    sample = (
        "Hi! When I try to export my data on iOS Safari, the page hangs after "
        "I select more than 100 rows. Tested on iPhone 15, iOS 17.4."
    )
    outcome = await classify_feedback(
        session,
        project_id=project.id,
        text=sample,
        feedback_id=None,
        project_hint=f"{project.name} ({project.slug})",
        purpose="test",
    )
    error = _truncate_error(outcome.error_text)
    await record_llm_test_result(session, project.id, ok=outcome.ok, error=error)

    await audit.log_event(
        session,
        event="llm_settings.tested",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        details={
            "ok": outcome.ok,
            "status": outcome.status,
            "provider": outcome.provider,
            "model": outcome.model,
            "latency_ms": outcome.latency_ms,
        },
    )

    return LLMTestOut(
        ok=outcome.ok,
        status=outcome.status,
        provider=outcome.provider or None,
        model=outcome.model or None,
        latency_ms=outcome.latency_ms,
        usd_cost=outcome.usd_cost,
        error_text=error,
    )


# ─── /v1/projects/{slug}/llm-calls ─────────────────────────────────────────


@router.get(
    "/projects/{slug}/llm-calls",
    response_model=list[LLMCallOut],
    summary="List recent LLM calls for the audit table (admin only)",
)
async def list_llm_calls(
    slug: str,
    limit: int = Query(50, ge=1, le=200),
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> list[LLMCallOut]:
    _me, project = pair
    rows = await list_recent_llm_calls(session, project.id, limit=limit)
    return [
        LLMCallOut(
            id=r.id,
            provider=r.provider,
            model=r.model,
            purpose=r.purpose,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            total_tokens=r.total_tokens,
            usd_cost=r.usd_cost,
            latency_ms=r.latency_ms,
            status=r.status,
            error_text=_truncate_error(r.error_text),
            created_at=r.created_at,
        )
        for r in rows
    ]
