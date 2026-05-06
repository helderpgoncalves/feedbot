"""Feedbot MCP server.

Thin stdio bridge between Claude Code and a Feedbot deployment.
The dev sets FEEDBOT_API_URL and FEEDBOT_API_KEY in their `.mcp.json`;
this process forwards tool calls to the hosted (or self-hosted) HTTP API.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from feedbot_mcp.client import FeedbotHTTP
from feedbot_mcp.settings import McpSettings

server = Server("feedbot")
_http: FeedbotHTTP | None = None


def _http_client() -> FeedbotHTTP:
    global _http
    if _http is None:
        s = McpSettings()
        if not s.api_key:
            raise RuntimeError("FEEDBOT_API_KEY is required")
        _http = FeedbotHTTP(s.api_url, s.api_key)
    return _http


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_feedbacks",
            description="List feedbacks in the project. Filter by status/type/severity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["new", "triaged", "in_progress", "done", "wont_fix"]},
                    "type": {"type": "string", "enum": ["bug", "feature", "question", "other"]},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        ),
        Tool(
            name="get_feedback",
            description="Get a single feedback by public id (FB-XXXXXX).",
            inputSchema={
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            },
        ),
        Tool(
            name="update_status",
            description="Change the status of a feedback. Optionally add a note.",
            inputSchema={
                "type": "object",
                "required": ["id", "status"],
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string", "enum": ["new", "triaged", "in_progress", "done", "wont_fix"]},
                    "note": {"type": "string"},
                },
            },
        ),
        Tool(
            name="add_note",
            description="Append a note to a feedback without changing status.",
            inputSchema={
                "type": "object",
                "required": ["id", "note"],
                "properties": {"id": {"type": "string"}, "note": {"type": "string"}},
            },
        ),
        Tool(
            name="reply_to_user",
            description="Queue a reply for the original author. Sent by the bot on next sync.",
            inputSchema={
                "type": "object",
                "required": ["id", "message"],
                "properties": {"id": {"type": "string"}, "message": {"type": "string"}},
            },
        ),
        Tool(
            name="get_stats",
            description="Project-wide feedback counts grouped by status.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="search_feedbacks",
            description="Search feedbacks by free-text query (basic substring on title+body).",
            inputSchema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 20}},
            },
        ),
    ]


def _text(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, default=str, indent=2))]


@server.call_tool()
async def call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
    http = _http_client()
    if name == "list_feedbacks":
        return _text(await http.list_feedbacks(**args))
    if name == "get_feedback":
        return _text(await http.get_feedback(args["id"]))
    if name == "update_status":
        return _text(await http.patch_feedback(args["id"], {"status": args["status"], "note": args.get("note")}))
    if name == "add_note":
        return _text(await http.patch_feedback(args["id"], {"note": args["note"]}))
    if name == "reply_to_user":
        return _text(await http.patch_feedback(args["id"], {"reply_to_user": args["message"]}))
    if name == "get_stats":
        return _text(await http.stats())
    if name == "search_feedbacks":
        rows = await http.list_feedbacks(limit=args.get("limit", 20))
        q = args["query"].lower()
        rows = [r for r in rows if q in r["title"].lower() or q in r["body"].lower()]
        return _text(rows)
    raise ValueError(f"unknown tool: {name}")


async def _run() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
