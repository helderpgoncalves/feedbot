"""Defence-in-depth security headers.

Tight defaults; the app only loads scripts/styles from itself plus the two
trusted CDNs (Tailwind + HTMX) used in templates/base.html. If you swap
either out, update the CSP accordingly.
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_CSP_PARTS = [
    "default-src 'self'",
    "script-src 'self' https://cdn.tailwindcss.com https://unpkg.com 'unsafe-inline'",
    "style-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
]
DEFAULT_CSP = "; ".join(_CSP_PARTS)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", DEFAULT_CSP)
        if os.getenv("FEEDBOT_BASE_URL", "").lower().startswith("https://"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
