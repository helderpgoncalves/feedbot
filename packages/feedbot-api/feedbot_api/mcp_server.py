"""Streamable-HTTP MCP server mounted at ``/mcp``.

Why this lives in feedbot-api (not feedbot-mcp):
    The feedbot-mcp package is a *stdio* bridge that proxies HTTP — useful before
    HTTP transport was widely available. With MCP Streamable HTTP we serve the
    protocol directly from the same process that owns the database, so:

      - one-tool-call = one HTTP round-trip (no extra process boundary)
      - auth uses the same `fbk_*` keys the rest of the API already validates
      - project-scope is automatic: a key is per-project, so the tools any
        Claude Code instance sees are exactly the tools for *that* project

Project-scope (per Anthropic docs https://code.claude.com/docs/en/mcp#project-scope):
    Each Claude Code workspace points at its own .mcp.json with its own key.
    Different workspaces ⇒ different keys ⇒ different projects ⇒ different data.
    The transport never needs to know the project — the key carries it.

Auth model:
    Every JSON-RPC call carries `Authorization: Bearer fbk_live_<...>`. The
    auth middleware below extracts the project once, attaches it to a
    contextvar, and tools read from that contextvar. We deliberately do not
    forward the raw header into tool args — keeps the surface minimal.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from feedbot_core.models import ApiKey, FeedbackStatus, FeedbackType, Project, Severity
from feedbot_core.repos import (
    authenticate_api_key,
    create_feedback,
    get_feedback_by_public_id,
    list_feedbacks,
    stats_for_project,
    update_feedback_status,
)
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from feedbot_api.deps import _sessionmaker

log = logging.getLogger("feedbot.mcp")

# Per-request project context, populated by McpAuthMiddleware before the
# JSON-RPC dispatcher reaches our tools.
_current_project: ContextVar[Project | None] = ContextVar("_current_project", default=None)
_current_key: ContextVar[ApiKey | None] = ContextVar("_current_key", default=None)


def _project() -> Project:
    p = _current_project.get()
    if p is None:
        # This is a programming error — middleware should have rejected the request.
        raise RuntimeError("MCP tool invoked without a resolved project")
    return p


def _key_can_write() -> bool:
    k = _current_key.get()
    return bool(k and k.scope != "read")


def _serialize_feedback(fb: Any, project: Project) -> dict[str, Any]:
    return {
        "id": fb.public_id,
        "project_slug": project.slug,
        "type": str(fb.type),
        "severity": str(fb.severity),
        "status": str(fb.status),
        "title": fb.title,
        "body": fb.body,
        "summary": fb.summary,
        "tags": fb.tags,
        "author_platform": fb.author_platform,
        "author_name": fb.author_name,
        "note": fb.note,
        "reply_to_user": fb.reply_to_user,
        "user_reply": fb.user_reply,
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
        "updated_at": fb.updated_at.isoformat() if fb.updated_at else None,
    }


# ─── FastMCP server + tool registry ─────────────────────────────────────────


def build_mcp_server() -> FastMCP:
    """Construct the FastMCP server and register tools.

    Returned as a function so importing this module is side-effect-free; the
    actual mount happens in app.py with `mcp.streamable_http_app()`.
    """
    mcp = FastMCP(
        name="feedbot",
        instructions=(
            "Read, triage, resolve, and converse with users about product feedback. "
            "You are scoped to a single Feedbot project. The user-facing IDs are FB-XXXXXX."
        ),
        # Mount the protocol at the sub-app root; FastAPI mounts the whole
        # sub-app at /mcp so the public URL is exactly https://.../mcp/.
        streamable_http_path="/",
        stateless_http=True,
    )

    sm = _sessionmaker()

    @mcp.tool(
        name="list_feedbacks",
        description="List feedback in the current project. "
        "Filter by status, type, severity. Returns the most recent first.",
    )
    async def list_feedbacks_tool(
        status: str | None = None,
        type: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        project = _project()
        s = FeedbackStatus(status) if status else None
        t = FeedbackType(type) if type else None
        sv = Severity(severity) if severity else None
        async with sm() as session:  # type: AsyncSession
            rows = await list_feedbacks(
                session, project.id, status=s, type=t, severity=sv, limit=max(1, min(200, limit))
            )
            return [_serialize_feedback(r, project) for r in rows]

    @mcp.tool(
        name="get_feedback",
        description="Get a single feedback by its public ID (FB-XXXXXX).",
    )
    async def get_feedback_tool(id: str) -> dict[str, Any]:
        project = _project()
        async with sm() as session:
            fb = await get_feedback_by_public_id(session, project.id, id)
            if not fb:
                raise ValueError(f"feedback {id} not found in project {project.slug}")
            return _serialize_feedback(fb, project)

    @mcp.tool(
        name="update_status",
        description="Change the status of a feedback. Optionally append a note. "
        "Status values: new, triaged, in_progress, done, wont_fix.",
    )
    async def update_status_tool(id: str, status: str, note: str | None = None) -> dict[str, Any]:
        if not _key_can_write():
            raise PermissionError("read-only API key cannot mutate feedback")
        project = _project()
        new_status = FeedbackStatus(status)
        async with sm() as session:
            fb = await get_feedback_by_public_id(session, project.id, id)
            if not fb:
                raise ValueError(f"feedback {id} not found")
            await update_feedback_status(session, fb, new_status, note)
            await session.commit()
            return _serialize_feedback(fb, project)

    @mcp.tool(
        name="add_note",
        description="Append a note to a feedback without changing its status.",
    )
    async def add_note_tool(id: str, note: str) -> dict[str, Any]:
        if not _key_can_write():
            raise PermissionError("read-only API key cannot mutate feedback")
        project = _project()
        async with sm() as session:
            fb = await get_feedback_by_public_id(session, project.id, id)
            if not fb:
                raise ValueError(f"feedback {id} not found")
            fb.note = (fb.note + "\n" if fb.note else "") + note
            await session.commit()
            return _serialize_feedback(fb, project)

    @mcp.tool(
        name="reply_to_user",
        description="Queue a reply for the original reporter. Sent by the bot on the next sync. "
        "Use this when you don't have enough info to resolve the feedback.",
    )
    async def reply_to_user_tool(id: str, message: str) -> dict[str, Any]:
        if not _key_can_write():
            raise PermissionError("read-only API key cannot mutate feedback")
        project = _project()
        async with sm() as session:
            fb = await get_feedback_by_public_id(session, project.id, id)
            if not fb:
                raise ValueError(f"feedback {id} not found")
            fb.reply_to_user = message
            await session.commit()
            return _serialize_feedback(fb, project)

    @mcp.tool(
        name="request_more_info",
        description="Ask the original reporter for more information. Same as reply_to_user, "
        "but also nudges status back to 'triaged' so it's clear the loop is open.",
    )
    async def request_more_info_tool(id: str, question: str) -> dict[str, Any]:
        if not _key_can_write():
            raise PermissionError("read-only API key cannot mutate feedback")
        project = _project()
        async with sm() as session:
            fb = await get_feedback_by_public_id(session, project.id, id)
            if not fb:
                raise ValueError(f"feedback {id} not found")
            fb.reply_to_user = question
            fb.status = FeedbackStatus.TRIAGED
            await session.commit()
            return _serialize_feedback(fb, project)

    @mcp.tool(
        name="get_stats",
        description="Project-wide feedback counts grouped by status.",
    )
    async def get_stats_tool() -> dict[str, Any]:
        project = _project()
        async with sm() as session:
            by_status = await stats_for_project(session, project.id)
        return {"by_status": by_status, "total": sum(by_status.values())}

    @mcp.tool(
        name="search_feedbacks",
        description="Search feedback by free-text query (substring on title + body).",
    )
    async def search_feedbacks_tool(query: str, limit: int = 20) -> list[dict[str, Any]]:
        project = _project()
        q = query.strip().lower()
        async with sm() as session:
            rows = await list_feedbacks(session, project.id, limit=max(1, min(200, limit * 5)))
        out = [r for r in rows if q in r.title.lower() or q in r.body.lower()][:limit]
        return [_serialize_feedback(r, project) for r in out]

    @mcp.tool(
        name="create_feedback",
        description="Create a new feedback row programmatically. "
        "Use sparingly — most feedback should arrive via Telegram/WhatsApp. "
        "Type values: bug, feature, question, other. "
        "Severity values: low, medium, high, critical.",
    )
    async def create_feedback_tool(
        title: str,
        body: str,
        type: str = "other",
        severity: str = "medium",
        author_name: str | None = None,
    ) -> dict[str, Any]:
        if not _key_can_write():
            raise PermissionError("read-only API key cannot mutate feedback")
        project = _project()
        async with sm() as session:
            fb = await create_feedback(
                session,
                project_id=project.id,
                title=title.strip(),
                body=body.strip(),
                type=FeedbackType(type),
                severity=Severity(severity),
                author_platform="mcp",
                author_id="claude-code",
                author_name=author_name,
            )
            await session.commit()
            return _serialize_feedback(fb, project)

    return mcp


# ─── Auth middleware ────────────────────────────────────────────────────────


class McpAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate every request to /mcp with a `fbk_*` Bearer token.

    Resolves the project once and stuffs it into the contextvars above so
    tools can read it without an extra DB hit. Returns proper JSON-RPC-shaped
    error responses on 401 so Claude Code surfaces them cleanly.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # OPTIONS preflight (Claude Code's HTTP transport sends them).
        if request.method == "OPTIONS":
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return _jsonrpc_error(401, "missing bearer token")
        raw = auth.split(" ", 1)[1].strip()

        sm = _sessionmaker()
        async with sm() as session:
            key = await authenticate_api_key(session, raw)
            if not key:
                return _jsonrpc_error(401, "invalid api key")
            project = await session.get(Project, key.project_id)
            if not project:
                return _jsonrpc_error(404, "project not found")
            await session.commit()

        token_p = _current_project.set(project)
        token_k = _current_key.set(key)
        try:
            return await call_next(request)
        finally:
            _current_project.reset(token_p)
            _current_key.reset(token_k)


def _jsonrpc_error(http_status: int, message: str) -> JSONResponse:
    """JSON-RPC-shaped error so Claude Code displays a useful message."""
    body = {
        "jsonrpc": "2.0",
        "error": {"code": -32000, "message": message},
        "id": None,
    }
    return JSONResponse(body, status_code=http_status)


__all__ = ["McpAuthMiddleware", "build_mcp_server"]
