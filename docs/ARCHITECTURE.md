# Architecture

Feedbot is a small, multi-tenant, hosted-or-self-hosted feedback pipeline. The core principle: **one HTTP API is the source of truth**; messaging adapters are thin clients, and Claude Code talks to the API directly via MCP-over-HTTP.

## Components

```
                                    ┌─────────────────────────┐
                                    │      Web Dashboard      │
                                    │  (Jinja + HTMX, served  │
                                    │   by feedbot-api)       │
                                    │   incl. /llm settings   │
                                    └────────────▲────────────┘
                                                 │ session cookie
                                                 │
┌──────────────┐  bot-token         ┌────────────┴────────────┐    SQL    ┌────────────┐
│ Telegram bot │ ──ingest──────────►│                         │──────────►│            │
│ (global, one │ ──ingest-reply────►│   feedbot-api           │           │ Postgres   │
│  process     │ ◄──outbound-pending│  (FastAPI)              │◄──────────│            │
│  serves N    │     (5s poll)      │                         │           └────────────┘
│  projects)   │                    │  /v1/feedbacks          │
└──────┬───────┘                    │  /v1/stats              │           ┌────────────┐
       │                            │  /v1/internal/*         │── HTTPS ─►│ OpenAI /   │
       │ sendMessage                │  /mcp  (Streamable HTTP)│           │ Anthropic  │
       ▼                            │  /login (magic link)    │           │  (LLM)     │
   Telegram chat                    │  /app/* (dashboard)     │           └────────────┘
                                    │  /app/.../llm settings  │
┌──────────────┐  Bearer fbk_*      │                         │
│  Claude Code │ ◄────/mcp HTTP────►│                         │
│  (any model) │      JSON-RPC      │                         │
└──────────────┘                    └─────────────────────────┘
```

## Data model

```
tenants ─< users ─< project_members ─► projects
        ─< invites                    ─< api_keys
                                      ─< chat_links     (telegram | whatsapp → project)
                                      ─< feedbacks      (FB-XXXXXX, scoped per project)
                                      ─< project_llm_settings  (1:1 — provider, encrypted key, budget)
                                      ─< llm_calls             (audit row per LLM call)
magic_link_tokens     (single-use email login)
chat_link_tokens      (deep-link onboarding, 15-min TTL)
telegram_updates      (idempotency)
```

Every row that belongs to "user data" carries `project_id` (and indirectly `tenant_id`). Authorization at the API layer derives the project from the API key's `project_id` (or, for MCP, from the Bearer token resolved by `McpAuthMiddleware`), so a key cannot read data from another project.

The `feedbacks` table also carries delivery-state columns introduced in M4 — `author_chat_id`, `reply_sent_at`, `reply_sent_message`, `notified_done_at`, `last_outbound_message_id`, `user_reply_at` — that drive the outbound queue and route reporter replies back to the right ticket.

## Auth

Three paths:

- **Web (humans):** magic-link via email. Single-use token → server-signed session cookie. Bootstrap path is `/setup` (only available while `users` is empty).
- **API / MCP (programs / Claude Code):** `Authorization: Bearer fbk_<env>_<random>`. Argon2-hashed in DB; only the prefix is stored visibly for support / log correlation. Same key validates `/v1/*` and `/mcp/`.
- **Bot ↔ API (server-to-server):** `FEEDBOT_BOT_TOKEN`, compared with `hmac.compare_digest`. Used only on `/v1/internal/*`. Endpoint returns 503 if unset (fail-closed).

Keys are scoped (`read` / `write` / `admin`) and revocable. Rotating a key is "create new, revoke old" — no downtime.

## MCP over Streamable HTTP

The API serves MCP natively at `/mcp/` using `FastMCP`, mounted on the same FastAPI app (lifespan composed so the FastMCP session manager runs alongside the API). Nine tools — `list_feedbacks`, `get_feedback`, `search_feedbacks`, `update_status`, `add_note`, `reply_to_user`, `request_more_info`, `create_feedback`, `get_stats`. Read-only keys cannot mutate.

Why HTTP over the old stdio bridge:

- One round-trip per tool call, no extra process boundary.
- Auth is the same `fbk_live_*` key the rest of the API validates — project-scope is automatic.
- HTTP is the [transport Anthropic recommends](https://code.claude.com/docs/en/mcp).
- Different Claude Code workspaces with different keys see different data — verified end-to-end with cross-project isolation tests.

The stdio package (`feedbot-mcp`) is deprecated, kept only for local-only fallback.

## LLM classification (M3)

Every inbound feedback can be auto-triaged with structured outputs:

- `feedbot_core/llm/` is the domain layer — `schema.Classification` (Pydantic), `base.ProviderProtocol`, a `register()` decorator, and a `get_provider()` factory.
- Providers (`providers/openai.py`, `providers/anthropic.py`) implement `ProviderProtocol` and self-register on import. Adding a new provider is one new file plus a registration call — the settings UI picks it up via `list_providers()` automatically.
- `crypto.py` Fernet-encrypts API keys at rest, with the Fernet key derived from `FEEDBOT_SECRET_KEY` via SHA-256.
- `pricing.py` is a `$/1M tokens` table per provider/model; cost is computed server-side so historical cost survives provider price changes.
- `classify_feedback()` does settings lookup → budget guard → dispatch → cost compute → audit. **It never raises** — failures are recorded in `llm_calls` and ingest continues.
- Per-project `monthly_budget_usd`: once the running total hits the cap, classification stops and is logged with `status=over_budget` until the next calendar month.

## Outbound delivery + conversational loop (M4)

The bot ↔ API protocol is queue-based, not push:

- Team queues a reply (`PATCH /v1/feedbacks/<id>` with `reply_to_user`) **or** Claude calls MCP `request_more_info`.
- Bot's `outbound_loop()` polls `/v1/internal/outbound-pending` every 5 seconds, delivers via Telegram Bot API, and ack's via `/v1/internal/outbound-ack`. The Telegram `message_id` is stored on the feedback row.
- Reporter replies (Telegram-reply) to one of the bot's messages → `on_user_reply_to_bot()` looks up the matching feedback by `last_outbound_message_id` and POSTs to `/v1/internal/ingest-reply`. Status flips back to `triaged`, body stored as `user_reply`.
- Status → `done` is queued the same way; bot posts `✅ FB-XXXXXX resolved.` once (guarded by `notified_done_at`).

`author_chat_id` is captured on every ingest, so the loop works even if the original reporter never DMs the bot.

## Why a monorepo

The four packages share a domain (the schema, the IDs, the meaning of `status=done`, the LLM classification contract). A change in one is almost always a change in another. Splitting them across repos would double the PR count and create stale-version drift between bot and API. Versioning is per-package; CI builds them independently.

## What is *not* in scope

- File attachments and Drive (will return as opt-in storage adapters).
- Bidirectional Google Sheet sync (legacy from the prototype; replaced by the dashboard).
- Multi-tenant managed WhatsApp (M5; M2 is self-hosted Baileys sidecar).
