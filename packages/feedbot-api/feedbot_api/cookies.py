"""Cookie + request helpers shared by every auth router.

Lifted out of ``routers/auth.py`` when the Jinja-served auth flow was deleted:
``v1_auth.py`` and the cookie-based dependencies still need these primitives,
so they live here in a router-free module that nobody mounts.

Two cookies live here:

* ``fb_session`` — the opaque server-side session id. HttpOnly, ``SameSite=Strict``,
  ``Secure`` when the public URL is HTTPS. The SPA and API are same-origin via
  the Caddy proxy, so Strict is safe.
* ``mlnonce`` — short-lived (15 min) PKCE-style binding. Set when a magic link
  is requested; checked on consumption. A mismatch flips the login into
  ``cross_device`` mode (link still works, but we audit + email).
"""

from __future__ import annotations

import hashlib
import os

from fastapi import Request, Response
from feedbot_core import auth_sessions

#: Cookie name for the server-side session id.
SESSION_COOKIE = "fb_session"

#: Short-lived httpOnly cookie that binds a magic-link to the browser that
#: requested it. Lifetime matches the magic-link TTL (15 min).
NONCE_COOKIE = "mlnonce"
NONCE_TTL_SECONDS = 60 * 15
NONCE_BYTES = 32


def is_https() -> bool:
    """Whether the public deployment is HTTPS — gates Secure cookie attribute."""
    return os.getenv("FEEDBOT_BASE_URL", "").lower().startswith("https://")


def hash_nonce(raw: str) -> str:
    """SHA-256 hex digest of the nonce. Used to compare cookie ↔ DB without
    storing the nonce itself in plaintext."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=int(auth_sessions.DEFAULT_TTL.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=is_https(),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def set_nonce_cookie(response: Response, raw_nonce: str) -> None:
    response.set_cookie(
        NONCE_COOKIE,
        raw_nonce,
        max_age=NONCE_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=is_https(),
        path="/",
    )


def clear_nonce_cookie(response: Response) -> None:
    response.delete_cookie(NONCE_COOKIE, path="/")


def client_ip(request: Request) -> str | None:
    """Real client IP, honouring Caddy / Coolify ``X-Forwarded-For``."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def client_user_agent(request: Request) -> str | None:
    """User-Agent capped to fit the audit log / sessions DB columns.

    Named ``client_user_agent`` (not ``user_agent``) to avoid colliding with
    the ``user_agent=`` kwarg every audit / sessions call uses.
    """
    ua = request.headers.get("user-agent")
    if not ua:
        return None
    return ua[:255]
