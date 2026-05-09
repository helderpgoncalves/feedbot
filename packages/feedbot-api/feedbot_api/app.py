"""FastAPI app entrypoint — wires routers and middleware.

This is a pure JSON API. The user-facing dashboard lives in ``apps/web``
and talks to this server through the same-origin Caddy proxy at ``/api/*``.
There is no HTML UI here any more — every UI surface that used to exist
under ``routers/dashboard.py`` / ``routers/team.py`` / ``routers/auth.py``
(GET handlers) etc. has moved to the SPA, and the JSON endpoints under
``/v1/*`` are the contract.

Surfaces still served by this process:

* ``/v1/*``      — the SPA's JSON API and the bot's ingestion path.
* ``/mcp/*``     — Streamable-HTTP MCP server for any MCP-compatible client.
* ``/healthz``   — liveness probe.
* ``/openapi.json`` / ``/docs`` / ``/redoc`` — OpenAPI surface (used by
  ``pnpm gen:api`` from the SPA).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from feedbot_api.email_backend import is_console_backend_unsafe_for_prod
from feedbot_api.mcp_server import McpAuthMiddleware, build_mcp_server
from feedbot_api.rate_limit import limiter
from feedbot_api.routers import (
    internal,
    v1,
    v1_admin_bot,
    v1_admin_email,
    v1_admin_proxy,
    v1_admin_system,
    v1_auth,
    v1_billing,
    v1_feedbacks,
    v1_llm,
    v1_projects,
    v1_team,
    v1_tenant,
)
from feedbot_api.security_headers import SecurityHeadersMiddleware

log = logging.getLogger("feedbot.api")
logging.basicConfig(
    level=os.getenv("FEEDBOT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


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

app.include_router(v1.router)
app.include_router(v1_auth.router)
app.include_router(v1_projects.router)
app.include_router(v1_feedbacks.router)
app.include_router(v1_llm.router)
app.include_router(v1_team.router)
app.include_router(v1_billing.router)
app.include_router(v1_billing.webhook_router)
app.include_router(v1_tenant.router)
app.include_router(v1_admin_email.router)
app.include_router(v1_admin_bot.router)
app.include_router(v1_admin_proxy.router)
app.include_router(v1_admin_system.router)
app.include_router(internal.router)

# Streamable-HTTP MCP server. The sub-app handles JSON-RPC; our auth middleware
# in front of it does Bearer validation and project resolution.
# Reference: https://code.claude.com/docs/en/mcp#option-1-add-a-remote-http-server
app.mount("/mcp", _mcp_app)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "ok": True,
        "email_backend": os.getenv("EMAIL_BACKEND", "console"),
        "email_backend_unsafe_for_prod": is_console_backend_unsafe_for_prod(),
    }
