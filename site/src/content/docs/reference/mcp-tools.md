---
title: MCP tools
description: The nine tools any MCP-compatible client can call against a Feedbot project via the /mcp endpoint.
---

The Feedbot API serves the [Model Context Protocol](https://modelcontextprotocol.io) natively over **Streamable HTTP** at `/mcp`. Auth is the same `fbk_live_*` API key the rest of the platform uses; project-scope is automatic — different keys see different data.

Any MCP-compatible client works: Claude Code, Claude Desktop, Cursor, Windsurf, Zed, Continue, custom agents using the MCP SDK, and so on. Below are snippets for the most common configurations.

## The easy way: copy the snippets from the dashboard

Open a project in your Feedbot dashboard, scroll to **Connect via MCP**, and copy the snippet for your client. The dashboard injects:

- The exact public URL of *your* deployment (cloud or self-hosted).
- The freshly-issued API key (only ever shown once — the same panel walks you through creating one).

Self-hosters with a custom domain get the same flow without any extra setup, as long as `FEEDBOT_PUBLIC_URL` (or `FEEDBOT_MCP_PUBLIC_URL` for split-domain deploys) is set on the web container.

## Wire it up manually

### Claude Code (CLI)

```bash
claude mcp add --transport http feedbot https://your-feedbot.example.com/mcp/ \
  --header "Authorization: Bearer fbk_live_..."
```

This mirrors Anthropic's [Option 1: Add a remote HTTP server](https://code.claude.com/docs/en/mcp#option-1-add-a-remote-http-server) example. The `feedbot` argument is the local server name — pick anything memorable (e.g. `feedbot-acme` if you wire multiple projects to one Claude Code).

### Claude Code, Cursor, Windsurf, Claude Desktop (JSON)

`.mcp.json` (Claude Code, Cursor, Windsurf) and `claude_desktop_config.json` (Claude Desktop) share the same shape:

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

### Any other MCP client

Any client that supports the Streamable HTTP transport with custom headers can talk to `/mcp`. The three pieces of information a client needs:

| Field          | Value                                              |
| -------------- | -------------------------------------------------- |
| URL            | `https://your-feedbot.example.com/mcp/`            |
| Transport      | Streamable HTTP                                    |
| Authorization  | `Authorization: Bearer fbk_live_...`               |

:::tip
Each workspace / agent uses its own API key. Same MCP server, isolated project data — guaranteed by the auth layer. Cross-project access is not possible regardless of which client connects.
:::

:::note[Self-host: pointing the dashboard at the right URL]
The web container reads two env vars at startup to render the snippets:

- `FEEDBOT_PUBLIC_URL` — base URL of the dashboard (default: `http://localhost:3000`). When the API and SPA share the same origin (the standard `docker compose` setup), `${FEEDBOT_PUBLIC_URL}/mcp/` is the correct MCP URL automatically.
- `FEEDBOT_MCP_PUBLIC_URL` — set this only when the API lives on a different domain (e.g. `app.example.com` for the SPA, `api.example.com` for the backend). Should be the **full** URL ending in `/mcp/`.

Both are surfaced via the runtime `/config.json` so the same Docker image works for every deployment without rebuilding.
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
