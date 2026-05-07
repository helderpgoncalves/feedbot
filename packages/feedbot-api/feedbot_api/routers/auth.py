"""Email magic-link login with server-side sessions and PKCE-style binding.

Three things changed vs. the original cookie-signed session:

1. **Server-side sessions.** The cookie ``fb_session`` carries an opaque token
   (32 bytes url-safe). Validation is a DB lookup against the ``sessions``
   table. Logout is a single UPDATE; "log out everywhere" is a bulk UPDATE.

2. **PKCE-style binding (lax + audit).** When the user submits ``POST /login``,
   the response sets a short-lived httpOnly ``mlnonce`` cookie carrying a
   32-byte nonce. Its hash is stored alongside the magic-link token. When the
   user opens the link, the same browser must present the cookie — if it does
   not, we log a ``login.cross_device`` audit event and email the user a "new
   sign-in detected" notice. The link still works (lax mode) because cutting
   off cross-device login would break legitimate "submit on PC, click on
   phone" flows.

3. **Cookie attributes.** ``fb_session`` is httpOnly, ``SameSite=Strict``, and
   ``Secure`` when the public URL is HTTPS. Strict is safe because the SPA and
   API are same-origin via the Caddy proxy in apps/web.

Hard cutover: any signed-cookie sessions that existed before 0006 are
invalid the moment this router replaces the previous one. Documented in
CHANGELOG under "Changed (BREAKING)".
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import secrets

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from feedbot_core import audit, auth_sessions
from feedbot_core.repos import consume_magic_link, get_user_by_email, issue_magic_link
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session
from feedbot_api.email_backend import (
    email_backend_from_env,
    is_console_backend_unsafe_for_prod,
)
from feedbot_api.rate_limit import limiter
from feedbot_api.templating import render

log = logging.getLogger("feedbot.auth")

router = APIRouter(tags=["auth"])

#: Cookie name for the server-side session id.
SESSION_COOKIE = "fb_session"

#: Short-lived httpOnly cookie that binds a magic-link to the browser that
#: requested it. Lifetime matches the magic-link TTL (15 min).
NONCE_COOKIE = "mlnonce"
NONCE_TTL_SECONDS = 60 * 15
NONCE_BYTES = 32


# ─── Helpers ──────────────────────────────────────────────────────────────


def _is_https() -> bool:
    """Whether the public deployment is HTTPS — gates Secure cookie attribute."""
    return os.getenv("FEEDBOT_BASE_URL", "").lower().startswith("https://")


def _hash_nonce(raw: str) -> str:
    """SHA-256 hex digest of the nonce. Used to compare cookie ↔ DB without
    storing the nonce itself in plaintext."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=int(auth_sessions.DEFAULT_TTL.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=_is_https(),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _set_nonce_cookie(response: Response, raw_nonce: str) -> None:
    response.set_cookie(
        NONCE_COOKIE,
        raw_nonce,
        max_age=NONCE_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=_is_https(),
        path="/",
    )


def _clear_nonce_cookie(response: Response) -> None:
    response.delete_cookie(NONCE_COOKIE, path="/")


def _client_ip(request: Request) -> str | None:
    # Caddy / Coolify forward the real client IP via X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    if not ua:
        return None
    # Cap to fit DB column without truncating mid-token.
    return ua[:255]


# ─── Routes ───────────────────────────────────────────────────────────────


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
                    "Email delivery is not configured on this deployment. "
                    "Set EMAIL_BACKEND=smtp and SMTP_* env vars."
                ),
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    user = await get_user_by_email(session, email)
    nonce_raw = secrets.token_urlsafe(NONCE_BYTES)
    nonce_hash = _hash_nonce(nonce_raw)

    if user is not None:
        token_raw = secrets.token_urlsafe(24)
        await issue_magic_link(session, email, token_raw, nonce_hash=nonce_hash)
        base = str(request.base_url).rstrip("/")
        link = f"{base}/login/verify?email={email}&token={token_raw}"
        # Swallow delivery failures: leaking them here would let attackers
        # enumerate which emails exist by timing/error-pattern analysis.
        with contextlib.suppress(Exception):
            email_backend_from_env().send(
                to=email,
                subject="Your Feedbot sign-in link",
                body=(
                    f"Sign in to Feedbot:\n\n{link}\n\n"
                    "This link expires in 15 minutes and can be used once. "
                    "If you didn't request this, you can ignore the email — "
                    "the link cannot be reused.\n"
                ),
            )

    # Always render the same response page whether the email exists or not —
    # prevents enumeration via timing or error patterns.
    response: Response = render(request, "login_sent.html", {"email": email})
    # Set the PKCE nonce cookie *unconditionally* — even when the email is
    # unknown — to avoid a different cookie behaviour signalling existence.
    _set_nonce_cookie(response, nonce_raw)
    return response


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

    ok, bound_nonce_hash = await consume_magic_link(session, email, token)
    if not ok:
        await audit.log_event(
            session,
            event="login.fail",
            tenant_id=user.tenant_id,
            user_id=user.id,
            ip=_client_ip(request),
            user_agent=_user_agent(request),
            details={"reason": "invalid_or_expired_link"},
        )
        return render(
            request,
            "login.html",
            {"error": "invalid or expired link"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # ── PKCE verdict (lax mode) ───────────────────────────────────────────
    cookie_nonce = request.cookies.get(NONCE_COOKIE)
    cross_device = (
        bound_nonce_hash is not None
        and (not cookie_nonce or _hash_nonce(cookie_nonce) != bound_nonce_hash)
    )

    # ── Issue the new server-side session ─────────────────────────────────
    db_session = await auth_sessions.create(
        session,
        user=user,
        user_agent=_user_agent(request),
        ip=_client_ip(request),
    )
    await audit.log_event(
        session,
        event=("login.cross_device" if cross_device else "login.ok"),
        tenant_id=user.tenant_id,
        user_id=user.id,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        details={"session_id_prefix": db_session.id[:8]},
    )

    # In cross-device mode, email the user so they notice if it wasn't them.
    if cross_device:
        with contextlib.suppress(Exception):
            email_backend_from_env().send(
                to=email,
                subject="New Feedbot sign-in",
                body=(
                    f"A new sign-in to your Feedbot account just happened from a "
                    f"different browser than the one that requested the magic link.\n\n"
                    f"  IP:         {_client_ip(request) or 'unknown'}\n"
                    f"  User-agent: {_user_agent(request) or 'unknown'}\n\n"
                    "If this was you, no action is needed.\n"
                    "If not, sign in again and revoke all sessions from /security.\n"
                ),
            )

    # Mirror email into the legacy SessionMiddleware cookie purely so the Jinja
    # `base.html` keeps showing the signed-in chrome until F7 removes the
    # template UI entirely. The authoritative identity source is the new
    # server-side `fb_session` cookie above.
    request.session["email"] = user.email

    redirect = RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(redirect, db_session.id)
    _clear_nonce_cookie(redirect)
    return redirect


@router.post("/logout")
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke the current session and clear the cookie."""
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        revoked = await auth_sessions.revoke(session, sid)
        if revoked:
            await audit.log_event(
                session,
                event="session.revoked",
                ip=_client_ip(request),
                user_agent=_user_agent(request),
                details={"reason": "user_logout", "session_id_prefix": sid[:8]},
            )
    # Clear the legacy SessionMiddleware cookie too (kept around for flash
    # messages on the Jinja UI). Will go away with the templates in F7.
    request.session.clear()

    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    _clear_session_cookie(response)
    return response
