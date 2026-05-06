# Architecture

Feedbot is a small, multi-tenant, hosted-or-self-hosted feedback pipeline. The core principle: **one HTTP API is the source of truth**; messaging adapters and the MCP server are thin clients.

## Components

```
                                    ┌─────────────────────────┐
                                    │      Web Dashboard      │
                                    │  (Jinja + HTMX, served  │
                                    │   by feedbot-api)       │
                                    └────────────▲────────────┘
                                                 │ session cookie
                                                 │
┌──────────────┐    Bearer fbk_*     ┌──────────┴──────────┐    SQL    ┌────────────┐
│ Telegram bot │ ───────────────────►│                     │──────────►│            │
│ (one per     │                     │   feedbot-api       │           │ Postgres   │
│  project)    │ ◄─────── reply ──── │  (FastAPI)          │◄──────────│            │
└──────────────┘                     │                     │           └────────────┘
                                     │  /v1/feedbacks      │
┌──────────────┐    Bearer fbk_*     │  /v1/stats          │
│  Claude Code │ ◄──────────────────►│  /login (magic link)│
│  + feedbot-  │      HTTP/HTTPS     │  /app/* (dashboard) │
│   mcp (stdio)│                     │                     │
└──────────────┘                     └─────────────────────┘
```

## Data model

```
tenants ─< users
        ─< projects ─< api_keys
                     ─< chat_links     (telegram | whatsapp → project)
                     ─< feedbacks      (FB-XXXXXX, scoped per project)
magic_link_tokens     (single-use email login)
telegram_updates      (idempotency)
```

Every row that belongs to "user data" carries `project_id` (and indirectly `tenant_id`). Authorization at the API layer derives the project from the API key's `project_id`, so a key cannot read data from another project.

## Auth

Two paths:

- **Web (humans):** magic-link via email. Issues a single-use token, lands the user in a server-signed session cookie.
- **API (programs / bots / MCP):** `Authorization: Bearer fbk_<env>_<random>`. Argon2-hashed in DB; only the prefix is stored visibly for support / log correlation.

Keys are scoped (`read` / `write` / `admin`) and revocable. Rotating a key is "create new, revoke old" — no downtime.

## The MCP server

Designed to be a thin client, not a smart middleware. It's <200 LOC: declare 7 tools, forward calls over HTTPS, return JSON. Putting logic here would force users to upgrade `feedbot-mcp` whenever the API changes; instead, the API evolves with versioned routes (`/v1`, `/v2`) and the MCP follows.

## Why a monorepo

The four packages share a domain (the schema, the IDs, the meaning of `status=done`). A change in one is almost always a change in another. Splitting them across repos would double the PR count and create stale-version drift between bot and API. Versioning is per-package; CI builds them independently.

## What is *not* in scope

- File attachments and Drive (will return as opt-in storage adapters).
- Bidirectional Google Sheet sync (legacy from the prototype; replaced by the dashboard).
- Multi-tenant managed WhatsApp (M3+; M2 is self-hosted Baileys sidecar).
