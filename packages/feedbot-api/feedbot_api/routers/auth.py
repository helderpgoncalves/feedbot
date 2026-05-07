"""Email magic-link login. Closed-loop: only existing users can authenticate."""

from __future__ import annotations

import contextlib
import secrets

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from feedbot_core.repos import consume_magic_link, get_user_by_email, issue_magic_link
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session
from feedbot_api.email_backend import email_backend_from_env, is_console_backend_unsafe_for_prod
from feedbot_api.rate_limit import limiter
from feedbot_api.templating import render

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> Response:
    return render(request, "login.html", {})


@router.post("/login")
@limiter.limit("5/15minutes")
async def login_submit(
    request: Request,
    email: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> Response:
    email = email.lower().strip()

    if is_console_backend_unsafe_for_prod():
        return render(
            request,
            "login.html",
            {
                "error": (
                    "Email delivery is not configured on this deployment. Set EMAIL_BACKEND=smtp and SMTP_* env vars."
                ),
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    user = await get_user_by_email(session, email)
    if user is not None:
        raw = secrets.token_urlsafe(24)
        await issue_magic_link(session, email, raw)
        base = str(request.base_url).rstrip("/")
        link = f"{base}/login/verify?email={email}&token={raw}"
        # Swallow delivery failures: leaking them here would let attackers
        # enumerate which emails exist by timing/error-pattern analysis.
        with contextlib.suppress(Exception):
            email_backend_from_env().send(
                to=email,
                subject="Your Feedbot sign-in link",
                body=f"Sign in to Feedbot:\n\n{link}\n\nThis link expires in 15 minutes.",
            )

    # Same response whether the email exists or not — prevents enumeration.
    return render(request, "login_sent.html", {"email": email})


@router.get("/login/verify")
@limiter.limit("10/15minutes")
async def login_verify(
    request: Request,
    email: str,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    email = email.lower().strip()
    user = await get_user_by_email(session, email)
    if user is None:
        return render(
            request,
            "login.html",
            {"error": "invalid or expired link"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    ok, _nonce_hash = await consume_magic_link(session, email, token)
    # PKCE binding (`_nonce_hash`) is wired up in F2.2 — for now we ignore it so
    # the existing magic-link flow continues to work unchanged.
    if not ok:
        return render(
            request,
            "login.html",
            {"error": "invalid or expired link"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    request.session["email"] = email
    return RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
async def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
