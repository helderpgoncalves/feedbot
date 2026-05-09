---
title: Changelog
description: Notable changes to Feedbot — added, changed, deprecated, fixed.
---

All notable changes to this project will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

_Nothing yet._

## [0.1.0] - 2026-05-09

### Added — Cloud v1.0 (C0–C5)

- **Cloud billing foundations (C0)** — `feedbot_core.billing/` with
  `assert_quota`, `current_plan`, `is_billing_enabled`. New
  `subscriptions` table (migration `0008`). Quota checks wired into
  `POST /v1/projects`, `POST /v1/internal/ingest`, `POST /v1/invites`
  with structured 402 responses. Self-host stays a no-op
  (`FEEDBOT_BILLING_ENABLED=false` short-circuits before any DB read).
- **Cloud signup (C1)** — `POST /v1/signup` with rate-limit `3/hour/IP`,
  anti-enumeration generic 200, and `is_signup_enabled()` gating. New
  SPA page `/signup`, login → signup link, route guards redirect
  empty-DB cloud deployments to `/signup` instead of `/setup`.
- **Stripe integration (C2)** — `feedbot_core.billing.stripe_client`
  using async `StripeClient` + `HTTPXClient`; webhook at
  `POST /v1/internal/stripe-webhook` with signature verification and
  event-id dedupe (`stripe_processed_events`, migration `0009`).
  Handlers for `customer.subscription.{created,updated,deleted}`,
  `invoice.payment_{succeeded,failed}`. Authed endpoints:
  `GET /v1/billing/subscription`, `POST /v1/billing/portal`,
  `POST /v1/billing/checkout`. Signup creates the Stripe customer +
  free-plan subscription on commercial cloud.
- **Billing UI (C3)** — owner-only `/billing` route with plan, status,
  usage bars, past-due alert, "Manage subscription" portal redirect,
  inline upgrade CTAs. `<UsageBanner />` on `/projects` shows yellow
  at ≥80% / red at ≥100% of any limit; renders `null` when billing
  is off. Sidebar "Billing" entry visible only to owners on cloud-
  with-billing.
- **GDPR export + delete (C4)** — `GET /v1/tenant/export` streams a
  zip with metadata + per-table json/csv (rate-limited 1/day);
  `POST /v1/tenant/delete` cascade-deletes after email reconfirm and
  best-effort cancels the Stripe subscription. New `/account` route
  with both surfaces. Legal pages live on the marketing site under
  `/legal/{terms,privacy,cookies,dpa}`.
- **Marketing consolidation** — removed `site/`, kept `apps/marketing/`
  as the single Astro+Starlight setup. Ported `pricing.mdx`,
  `@astrojs/sitemap`, `starlight-theme-black`, and Geist fonts. Custom
  landing at `/`, docs at `/docs/*`, sitemap at `/sitemap-index.xml`.
- **OG image** — generated 1200×630 PNG via `sharp` from a hand-rolled
  SVG (`apps/marketing/scripts/generate-og.mjs`); served from both the
  marketing site and the SPA.
- **Operational docs** — `docs/DEPLOY-COOLIFY.md` §8 covers Sentry,
  structured logs, status page, restore drill, and on-call. The next-
  steps block lists the Stripe env vars commercial cloud needs.

### Changed — Cloud v1.0

- **`apps/web/src/lib/config.ts`** — `RuntimeConfig` gained
  `billingEnabled`. Self-host default is `false`.
- **Caddy entrypoint** of `apps/web` already templated `billingEnabled`
  / `allowSignup` — these now thread all the way to the SPA UI.

### Removed
- **Jinja UI in `feedbot-api` (BREAKING)** — the legacy server-rendered dashboard, team page, members page, invites accept page, login form, LLM settings page, and bootstrap setup wizard have been deleted. The SPA in `apps/web/` has full functional parity and is now the only UI. The API process is a pure JSON server. Concretely removed: `routers/auth.py`, `routers/dashboard.py`, `routers/team.py`, `routers/members.py`, `routers/invites.py`, `routers/llm_settings.py`, `routers/setup.py`, the entire `templates/` and `static/` directories, `templating.py`, the `SessionMiddleware`, and the dependencies `jinja2`, `python-multipart`, `itsdangerous`.
- **GET /, GET /login, GET /login/verify, GET /setup, GET /dashboard, /team, /members, /invites/{token}** (HTML responses) and the unversioned **POST /login**, **POST /logout**, **POST /setup** form handlers. Use the SPA at `app.<host>` (or whatever `FEEDBOT_PUBLIC_URL` points to) which talks to `/v1/auth/*` and `/v1/setup`.
- **Bridge `request.session["email"]` cookie** that mirrored auth state into the legacy SessionMiddleware so the Jinja header could render the signed-in chrome. Server-side sessions (`fb_session`) are now the sole identity source.

### Changed
- **Bootstrap flow moved into `/v1/`** — first-run setup is now `GET /v1/setup-status` + `POST /v1/setup` (JSON), driven by a new SPA page at `/setup`. The `/v1/setup-status` check is cheap, public, and cached for 5 minutes; route guards in `(auth)` and `(authed)` redirect to `/setup` when the users table is empty.
- **Magic-link emails point at `/magic`** (the SPA route) for new logins. The old `/login/verify` redirect target is gone with the Jinja routes.
- Cookie / request helpers moved out of `routers/auth.py` into a new router-free `feedbot_api/cookies.py` module — no more circular-import dance, single source of truth for `fb_session` / `mlnonce`. Public function names dropped the leading underscore (`client_ip`, `set_session_cookie`, …); `user_agent` is now `client_user_agent` to avoid colliding with the keyword arg of every audit / sessions call.

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

