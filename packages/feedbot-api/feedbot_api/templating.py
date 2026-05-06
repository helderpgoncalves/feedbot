"""Jinja templates + a small helper that's compatible with the
post-Starlette-1.0 ``TemplateResponse`` signature (request goes first).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render a Jinja template into an HTMLResponse.

    Wraps `templates.TemplateResponse(request, name, context, status_code=...)`
    so callers don't have to remember to pass `request` (or to put it inside
    the context dict, which the new Starlette API rejects).
    """
    return templates.TemplateResponse(request, name, context or {}, status_code=status_code)
