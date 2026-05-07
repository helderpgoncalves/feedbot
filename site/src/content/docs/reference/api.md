---
title: HTTP API
description: REST endpoints exposed by feedbot-api — public, internal (bot-only), and admin.
---

The API is FastAPI under the hood. Three groups of routes:

- **Public-ish** (`/v1/*`) — authenticated by `Authorization: Bearer fbk_<env>_<random>` API keys.
- **Internal** (`/v1/internal/*`) — authenticated by `FEEDBOT_BOT_TOKEN` (server-to-server only, never exposed to clients).
- **Web** (`/login`, `/setup`, `/app/*`) — magic-link cookies for human users.

This page covers the API-key surface — what your scripts, integrations, and the MCP server use. For the dashboard side (auth, invites, team management) the source is `packages/feedbot-api/feedbot_api/routers/`.

## Auth

```http
Authorization: Bearer fbk_live_AbCdEf12...
```

API keys are scoped (`read` / `write` / `admin`) and Argon2id-hashed at rest. Only the `fbk_<env>_<8>` prefix is stored visibly. A 401 always returns the same body — no enumeration.

## Feedbacks

### `POST /v1/feedbacks`

Create a feedback. Same shape the bot uses on inbound messages.

```bash
curl -s -X POST https://your-feedbot.example.com/v1/feedbacks \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Export crashes on iOS",
    "body": "Hangs >100 rows.",
    "type": "bug",
    "severity": "high",
    "author_platform": "web",
    "author_id": "u-123",
    "author_name": "Maria"
  }'
```

Returns `201` with the created row, including the assigned `id` (`FB-XXXXXX`). If LLM auto-triage is enabled, `type` / `severity` / `summary` / `tags` may be overwritten by the classifier *after* the row is created.

### `GET /v1/feedbacks`

List feedbacks for the project the key belongs to. Query params: `status`, `type`, `severity`, `limit`.

### `GET /v1/feedbacks/{id}`

Single feedback by `FB-XXXXXX`.

### `PATCH /v1/feedbacks/{id}`

Update status, append a note, or queue an outbound reply:

```json
{
  "status": "in_progress",
  "note": "investigating",
  "reply_to_user": "Which iOS version are you on?"
}
```

Each field is optional. `reply_to_user` queues a delivery to the chat where the feedback was reported (M4 outbound worker) — within ~5 seconds the bot posts `[FB-XXXXXX] Which iOS version are you on?` in that chat.

## Stats

### `GET /v1/stats`

Counts grouped by status. Cheap call.

```json
{
  "new": 12,
  "triaged": 5,
  "in_progress": 2,
  "done": 87,
  "wontfix": 3
}
```

## MCP

### `POST /mcp/`

Streamable-HTTP endpoint for the [Model Context Protocol](https://modelcontextprotocol.io). See [MCP tools](/reference/mcp-tools/) for the tool catalog.

## Internal endpoints (bot-token only)

These are not for clients — they require `FEEDBOT_BOT_TOKEN` and return `503` if it's unset. Documented for completeness.

| Endpoint | Purpose |
|---|---|
| `POST /v1/internal/ingest` | Bot pushes a fresh inbound message (creates a feedback). |
| `POST /v1/internal/redeem-link` | Atomically bind a `chat_id` to a project via deep-link token. |
| `GET  /v1/internal/outbound-pending` | Bot polls for queued replies and `done` notifications. |
| `POST /v1/internal/outbound-ack` | Bot confirms delivery; stores the Telegram `message_id`. |
| `POST /v1/internal/ingest-reply` | Bot routes a reporter's Telegram-reply back to the matching feedback. |

## Errors

| Status | Meaning |
|---|---|
| `401` | Missing or invalid Bearer token. |
| `403` | Read-only key attempting a mutation. |
| `404` | Feedback not found *in this project* (cross-project leakage protection). |
| `422` | Validation error — the body shape doesn't match the schema. |
| `429` | Rate limited. Most endpoints have generous defaults; auth routes are tight. |
| `503` | Bot ingestion disabled (server-side `FEEDBOT_BOT_TOKEN` unset), or email backend misconfigured. |

## OpenAPI schema

FastAPI publishes the full schema at `/openapi.json` and a Swagger UI at `/docs` (only when `FEEDBOT_OPENAPI_PUBLIC=true` in the env — disabled by default in production).
