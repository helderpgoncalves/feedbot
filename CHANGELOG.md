---
title: Changelog
description: Notable changes to Feedbot — added, changed, deprecated, fixed.
---

All notable changes to this project will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Outbound notification worker (M4)** — when status flips to `done` or the team queues a `reply_to_user`, the bot delivers the message back to the **same chat** where the feedback was first reported. Conversation stays in one thread; reporters never have to open a DM with the bot.
- **Conversation loop** — when a user replies in chat to one of the bot's messages, the body is captured as `user_reply`, status flips to `triaged`, and Claude (or a human) sees it on the next read. The MCP `request_more_info` tool now closes the loop end-to-end.
- **Outbound queue + audit columns** on `feedbacks`: `author_chat_id`, `reply_sent_at`, `reply_sent_message`, `notified_done_at`, `last_outbound_message_id`, `user_reply_at`. Migration `0005_feedback_delivery_tracking.py`.
- **Bot endpoints** — `/v1/internal/outbound-pending` (bot polls), `/v1/internal/outbound-ack`, `/v1/internal/ingest-reply`. All bot-token authenticated.
- **Bot delivery loop** — every 5 seconds the bot pulls the queue, delivers via Telegram Bot API, ack's back. Telegram `message_id` is stored so subsequent user-replies can be matched to the right feedback.
- **LLM-powered classification** — every inbound feedback can be auto-triaged into `type`, `severity`, `summary`, `tags`, `language`, `sentiment` using OpenAI or Anthropic structured outputs. Configured per project via `/app/projects/<slug>/llm`, with the API key encrypted at rest using a Fernet key derived from `FEEDBOT_SECRET_KEY`.
- **Provider plug-in registry** in `feedbot_core/llm/` — adding a new provider (Gemini, Groq, Ollama…) is one new file with a `@register("name")` class that implements `ProviderProtocol`. The settings UI picks it up automatically. OpenAI and Anthropic ship out of the box.
- **Cost tracking** — every LLM call writes a row to `llm_calls` with `provider`, `model`, `input_tokens`, `output_tokens`, `usd_cost`, `latency_ms`, `status`. The settings page shows month-to-date spend and the last 50 calls. Pricing is computed server-side from `feedbot_core/llm/pricing.py` so historical costs survive provider price changes.
- **Monthly budget** — optional `monthly_budget_usd` per project. When the running total hits the cap, classification stops and is logged with `status=over_budget` until the next calendar month.
- **`Test connection` button** on the LLM settings page — runs a real classification round-trip against a sample input and stores the outcome (`last_test_ok`, `last_test_error`).
- **Structured logging** for every LLM call (provider, model, tokens, cost, latency, status, project, feedback id).
- **MCP via Streamable HTTP at `/mcp`** — the Feedbot API serves the MCP protocol natively now, no proxy process. Auth is the same `fbk_live_*` API key the rest of the platform uses. Project-scope is automatic: a key carries its project, so different Claude Code workspaces with different keys see different data — verified end-to-end with cross-project isolation tests. Wire up with `claude mcp add feedbot --transport http --header "Authorization: Bearer ..." https://.../mcp/` (per [docs](https://code.claude.com/docs/en/mcp)).
- **MCP tools**: `list_feedbacks`, `get_feedback`, `update_status`, `add_note`, `reply_to_user`, `request_more_info` (asks the reporter for more info and resets status to `triaged`), `get_stats`, `search_feedbacks`, `create_feedback`. Read-only keys cannot mutate.
- **First-run setup (`/setup`)** — Coolify-style onboarding when the database is empty. Creates the owner account and sends them the first magic link.
- **Roles**: `owner`, `admin`, `member`. Members only see projects they were explicitly added to.
- **Invites** with 7-day single-use tokens, sent via email by the team admin.
- **Per-project membership** — admins assign members to projects from the project page.
- **Ownership transfer** — owners can hand the role to another admin.
- **Email backends** — `console` for dev, `smtp` (TLS / STARTTLS) for production.
- **Security headers** middleware — HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy.
- **Rate limiting** via `slowapi` on `/login`, `/setup`, `/invites/*`, with sane defaults elsewhere.
- **Coolify deployment guide** (`docs/DEPLOY-COOLIFY.md`) with managed-Postgres + SMTP walkthrough.
- Multi-project routing: one Telegram bot serves N projects, project resolved from `chat_id` via `chat_links`.
- Deep-link onboarding (`t.me/<bot>?startgroup=link_<token>`) — single-use 15-min tokens, atomic redeem.
- Internal endpoints `/v1/internal/{ingest,redeem-link}` authenticated with server-side `FEEDBOT_BOT_TOKEN`.
- Dashboard: connect / disconnect chats per project, with deep-link button.
- `scripts/seed.py` — non-interactive project + key creation.
- Architecture, deployment, and E2E docs.

### Changed
- **Login is closed**: `/login` no longer auto-creates accounts. Same response whether the email exists or not (no enumeration).
- Magic-link refused when `EMAIL_BACKEND=console` and `FEEDBOT_BASE_URL` is `https://` — prevents silently broken production deployments.
- Session cookies are now `https_only` when serving over HTTPS, `same_site=lax`.

### Deprecated
- The `feedbot-mcp` stdio package is deprecated in favor of `/mcp` HTTP. It still works for local-only setups but new deployments should use the HTTP endpoint.

## [0.1.0] - planned

Initial public release: capture (Telegram), triage (dashboard), resolve (MCP server).
