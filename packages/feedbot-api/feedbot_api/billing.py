"""Glue between ``feedbot_core.billing`` and FastAPI routes.

The core billing module is HTTP-agnostic — it raises ``QuotaExceeded`` and
lets the API decide how to surface it. This thin shim does that translation
so every router can emit the same structured 402 body without duplicating
the formatting.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, status
from feedbot_core.billing import QuotaExceeded


def _upgrade_url() -> str:
    """Return the URL the SPA should send users to for an upgrade.

    Cloud commercial points at our own billing page; cloud free-beta and
    self-host technically never raise QuotaExceeded (because billing is
    disabled), so the fallback is mostly cosmetic — but we still surface
    the same key so SPAs don't have to branch.
    """
    base = os.environ.get("FEEDBOT_PUBLIC_URL", "").rstrip("/")
    return f"{base}/billing" if base else "/billing"


def http_402_from(exc: QuotaExceeded) -> HTTPException:
    """Translate a ``QuotaExceeded`` into a 402 with a structured body.

    Frontend contract (mirrors the same shape across all routes):
        {
            "detail": "quota exceeded",
            "kind":   "project" | "feedback" | "member",
            "current": 5,
            "limit":   5,
            "upgrade_url": "https://app.feedbot.dev/billing"
        }
    """
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "detail": "quota exceeded",
            "kind": exc.kind,
            "current": exc.current,
            "limit": exc.limit,
            "upgrade_url": _upgrade_url(),
        },
    )
