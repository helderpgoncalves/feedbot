---
title: MCP tools
description: The nine tools Claude Code can call against a Feedbot project via the /mcp endpoint.
---

The Feedbot API serves the [Model Context Protocol](https://modelcontextprotocol.io) natively over **Streamable HTTP** at `/mcp`. Auth is the same `fbk_live_*` API key the rest of the platform uses; project-scope is automatic — different keys see different data.

## Wire it up

```bash
claude mcp add feedbot \
  --transport http \
  --header "Authorization: Bearer fbk_live_..." \
  https://your-feedbot.example.com/mcp/
```

Or commit a project-scoped `.mcp.json`:

```json
{
  "mcpServers": {
    "feedbot": {
      "type": "http",
      "url": "https://your-feedbot.example.com/mcp/",
      "headers": {
        "Authorization": "Bearer fbk_live_..."
      }
    }
  }
}
```

:::tip
Each Claude Code workspace has its own `.mcp.json` with a key for that project. Same MCP server, isolated data — guaranteed by the auth layer.
:::

## The tools

Read-only keys cannot mutate. All tools accept JSON-RPC 2.0 calls and return JSON.

### `list_feedbacks`

Filter by `status` / `type` / `severity`. Returns the most recent N matches.

> *"What's in the new bug pile?"*

### `get_feedback`

Look up a feedback by its `FB-XXXXXX` ID.

> *"Pull up FB-A3F2."*

### `search_feedbacks`

Substring search across title and body.

> *"Have we seen this export crash before?"*

### `update_status`

Move a feedback to `triaged`, `in_progress`, `done`, or `wontfix`. Optional `note` field is appended to the audit trail.

When status flips to `done`, the bot posts `✅ FB-XXXXXX resolved.` in the chat where the feedback was first reported.

> *"Mark FB-A3F2 done — fixed in PR #91."*

### `add_note`

Append a note to a feedback without changing its status.

> *"Note on FB-B7C1: needs design review."*

### `reply_to_user`

Queue a reply that will be delivered **to the same chat** the feedback was reported in, prefixed with `[FB-XXXXXX]`. The bot's outbound loop polls every 5 seconds and delivers via Telegram Bot API.

> *"Tell the reporter of FB-A3F2 it's fixed in v2.4.0."*

### `request_more_info`

Like `reply_to_user`, but also resets the status back to `triaged`. Use this when you can't act on the feedback without more info from the reporter.

When the reporter Telegram-replies to the bot's question, the body is captured as `user_reply` on the feedback row, and the ticket surfaces on your next `list_feedbacks` call.

> *"Ask the reporter for their iOS version."*

### `create_feedback`

Programmatic creation — useful when Claude spots an issue itself while reviewing code or logs.

### `get_stats`

Counts grouped by status. Cheap call, useful as a starting point.

> *"How's the pipeline?"*

## How auth works

The MCP server is mounted on the same FastAPI app via `FastMCP`. A `McpAuthMiddleware` reads the `Authorization: Bearer …` header on every JSON-RPC call, looks up the key by Argon2 prefix, and resolves the project. Mutations are blocked for read-only keys.

Cross-project isolation is enforced by the same `project_members` join the rest of the API uses. Verified end-to-end: a key for project A cannot read or write project B's rows.

## Curl smoke test

```bash
KEY="fbk_live_..."
URL="https://your-feedbot.example.com/mcp/"

# initialize
curl -s -X POST "$URL" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'

# list tools
curl -s -X POST "$URL" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}'
```
