"""Per-project LLM settings page + test endpoint.

Admin-only (require_project_admin). The page lists all registered providers
dynamically from feedbot_core.llm.list_providers() — adding a new provider in
the registry makes it appear here without any HTML edit.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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

from feedbot_api.deps import get_session, require_project_admin
from feedbot_api.templating import render

log = logging.getLogger("feedbot.api.llm")

router = APIRouter(prefix="/app/projects/{slug}/llm", tags=["llm-settings"])


@router.get("", response_class=HTMLResponse)
async def llm_home(
    slug: str,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    me, project = pair
    settings = await get_or_create_llm_settings(session, project.id)
    calls = await list_recent_llm_calls(session, project.id, limit=50)
    mtd = await llm_month_to_date_cost(session, project.id)

    return render(
        request,
        "llm_settings.html",
        {
            "me": me,
            "project": project,
            "settings": settings,
            "providers": list_providers(),
            "calls": calls,
            "month_to_date_usd": mtd,
            "has_key": settings.encrypted_api_key is not None,
        },
    )


@router.post("")
async def llm_save(
    slug: str,
    provider: str = Form(...),
    model: str = Form(""),
    api_key: str = Form(""),
    enabled: str = Form(""),
    monthly_budget_usd: str = Form(""),
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    _me, project = pair
    providers = list_providers()
    if provider != "none" and provider not in providers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown provider: {provider}")

    encrypted = encrypt_key(api_key.strip()) if api_key.strip() else None
    budget = float(monthly_budget_usd) if monthly_budget_usd.strip() else None

    await save_llm_settings(
        session,
        project.id,
        provider=provider,
        model=model.strip() or None,
        encrypted_api_key=encrypted,
        enabled=bool(enabled),
        monthly_budget_usd=budget,
    )
    return RedirectResponse(f"/app/projects/{slug}/llm", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/test")
async def llm_test(
    slug: str,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Run a single classification round-trip and record the result. Useful so
    admins can verify keys + model availability before ingest depends on it.
    """
    _me, project = pair
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
    await record_llm_test_result(session, project.id, ok=outcome.ok, error=outcome.error_text)
    return RedirectResponse(f"/app/projects/{slug}/llm", status_code=status.HTTP_303_SEE_OTHER)
