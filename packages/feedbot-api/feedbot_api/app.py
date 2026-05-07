"""FastAPI app entrypoint — wires routers, middleware, and the bootstrap gate."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from feedbot_core.repos import count_users
from feedbot_core.settings import CoreSettings
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from feedbot_api.deps import _sessionmaker
from feedbot_api.email_backend import is_console_backend_unsafe_for_prod
from feedbot_api.mcp_server import McpAuthMiddleware, build_mcp_server
from feedbot_api.rate_limit import limiter
from feedbot_api.routers import (
    auth,
    dashboard,
    internal,
    invites,
    llm_settings,
    members,
    setup,
    team,
    v1,
    v1_auth,
    v1_llm,
    v1_projects,
    v1_team,
)
from feedbot_api.security_headers import SecurityHeadersMiddleware
from feedbot_api.templating import render

log = logging.getLogger("feedbot.api")
logging.basicConfig(
    level=os.getenv("FEEDBOT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

settings = CoreSettings()
_https = os.getenv("FEEDBOT_BASE_URL", "").lower().startswith("https://")

# Build MCP first so we can compose its lifespan into ours.
_mcp = build_mcp_server()
_mcp_app = _mcp.streamable_http_app()
_mcp_app.add_middleware(McpAuthMiddleware)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run alongside FastMCP's session-manager lifespan.

    FastMCP's streamable-HTTP app holds an internal task group that has to be
    entered with ``run()`` for tool dispatch to work. When we mount it as a
    sub-app we have to drive that lifespan ourselves.
    """
    if is_console_backend_unsafe_for_prod():
        log.warning(
            "EMAIL_BACKEND=console on a public HTTPS deployment — magic links "
            "will not be delivered to users. Set EMAIL_BACKEND=smtp before opening "
            "this instance to non-admins."
        )
    async with _mcp.session_manager.run():
        yield


app = FastAPI(title="Feedbot", version="0.1.0", lifespan=lifespan)

# Rate-limit (process-local; slowapi's default in-memory store).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# HTTP security headers + HSTS when serving over HTTPS.
app.add_middleware(SecurityHeadersMiddleware)

# Signed session cookie. https_only flips ON when FEEDBOT_BASE_URL is https://.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=_https,
    same_site="lax",
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(v1.router)
app.include_router(v1_auth.router)
app.include_router(v1_projects.router)
app.include_router(v1_llm.router)
app.include_router(v1_team.router)
app.include_router(internal.router)
app.include_router(setup.router)
app.include_router(auth.router)
app.include_router(invites.router)
app.include_router(team.router)
app.include_router(members.router)
app.include_router(llm_settings.router)
app.include_router(dashboard.router)

# Streamable-HTTP MCP server. The sub-app handles JSON-RPC; our auth middleware
# in front of it does Bearer validation and project resolution.
# Reference: https://code.claude.com/docs/en/mcp#option-1-add-a-remote-http-server
app.mount("/mcp", _mcp_app)


# ─── Bootstrap gate ─────────────────────────────────────────────────────────


_PASS_PREFIXES = ("/setup", "/static", "/healthz", "/v1/internal", "/v1", "/mcp")


@app.middleware("http")
async def bootstrap_gate(request: Request, call_next):
    """Redirect humans to /setup while the users table is empty.

    REST + internal endpoints (/v1/*, /mcp) are exempt — they never trigger
    the bootstrap UI and their auth is independent.
    """
    path = request.url.path
    if path == "/setup" or any(path.startswith(p) for p in _PASS_PREFIXES):
        return await call_next(request)

    sm = _sessionmaker()
    async with sm() as session:
        try:
            empty = (await count_users(session)) == 0
        except Exception:
            empty = False

    if empty and request.method == "GET":
        return RedirectResponse("/setup", status_code=303)
    return await call_next(request)


# ─── Public pages ───────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> Response:
    return render(request, "landing.html", {})


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "ok": True,
        "email_backend": os.getenv("EMAIL_BACKEND", "console"),
        "email_backend_unsafe_for_prod": is_console_backend_unsafe_for_prod(),
    }
