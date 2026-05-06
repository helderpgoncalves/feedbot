"""First-run setup. Active only while the users table is empty.

Once the owner is created, this router refuses every request with 410. The
auth middleware in app.py does the redirect-to-/setup; this module is just
the form + handler.
"""

from __future__ import annotations

import contextlib
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from feedbot_core.repos import bootstrap_owner, count_users, issue_magic_link
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session
from feedbot_api.email_backend import email_backend_from_env, is_console_backend_unsafe_for_prod
from feedbot_api.rate_limit import limiter
from feedbot_api.templating import render

router = APIRouter(tags=["setup"])


async def _refuse_if_setup_done(session: AsyncSession) -> None:
    if (await count_users(session)) > 0:
        raise HTTPException(status.HTTP_410_GONE, "setup already complete")


@router.get("/setup", response_class=HTMLResponse)
async def setup_form(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    await _refuse_if_setup_done(session)
    return render(request, "setup.html", {})


@router.post("/setup")
@limiter.limit("3/15minutes")
async def setup_submit(
    request: Request,
    email: str = Form(...),
    tenant_name: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _refuse_if_setup_done(session)
    email = email.lower().strip()
    tenant_name = tenant_name.strip()

    user = await bootstrap_owner(session, email=email, tenant_name=tenant_name)

    raw = secrets.token_urlsafe(24)
    await issue_magic_link(session, user.email, raw)
    base = str(request.base_url).rstrip("/")
    link = f"{base}/login/verify?email={user.email}&token={raw}"

    if is_console_backend_unsafe_for_prod():
        # In the rare case someone bootstraps a public HTTPS deployment without
        # SMTP, surface the link directly so they aren't locked out of their own
        # instance. This is a one-time event and the URL is single-use + 15-min TTL.
        return render(
            request,
            "setup_done.html",
            {"email": user.email, "fallback_link": link},
        )

    delivered = False
    with contextlib.suppress(Exception):
        email_backend_from_env().send(
            to=user.email,
            subject="Welcome to Feedbot — sign in",
            body=f"You're the owner of this Feedbot instance.\nSign in:\n\n{link}\n",
        )
        delivered = True

    return render(
        request,
        "setup_done.html",
        {
            "email": user.email,
            "fallback_link": None if delivered else link,
        },
    )
