---
title: Deploy on Coolify
description: Step-by-step guide to running Feedbot on Coolify with managed Postgres, TLS, and automatic deploys. Twenty-five minutes end-to-end.
---

# Deploy Feedbot to Coolify

Step-by-step guide to running Feedbot on a [Coolify](https://coolify.io/) instance with TLS, automatic deploys, and a managed Postgres. Estimated time: **25 minutes**.

Feedbot ships as **two services**: a JSON API (`feedbot-api`) on `:8000`, and a static SPA (`apps/web`) served by Caddy on `:80`. The SPA's Caddy reverse-proxies `/api/*` and `/mcp/*` back to the API container, so users see a single same-origin host and cookies stay `SameSite=Strict`. You can deploy them under one domain (`app.example.com`) or two (`app.example.com` + `api.example.com`); both are supported.

---

## What you'll end up with

```
                       https://app.your-domain.com
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────┐
   │                Coolify (Caddy/Traefik + Docker)          │
   │                                                          │
   │   ┌────────────────────┐         ┌────────────────────┐  │
   │   │  web (Caddy + SPA) │ ──────► │  api (FastAPI)     │  │
   │   │  :80               │ /api,   │  :8000             │  │
   │   │                    │ /mcp,   │                    │  │
   │   │                    │ /login  │                    │  │
   │   └────────────────────┘         └─────────┬──────────┘  │
   │                                            │             │
   │                                            ▼             │
   │                                  ┌────────────────────┐  │
   │                                  │  postgres (managed)│  │
   │                                  └────────────────────┘  │
   │                                                          │
   │   ┌────────────────────┐ (optional, opt-in via profile)  │
   │   │  bot  (Telegram)   │ ─► api (server-to-server)       │
   │   └────────────────────┘                                 │
   └──────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- Coolify v4+ self-hosted **or** Coolify Cloud.
- A domain pointing at your server (e.g. `app.example.com → A record → server IP`). For split-domain setups, point both `app.example.com` and `api.example.com`.
- An SMTP provider (Resend, Postmark, SES, Brevo — any). Without one, magic-link login is disabled in production (`/v1/auth/login` returns 503).
- (Optional) A Telegram bot token from `@BotFather`.

---

## 1. Create the Postgres database

In Coolify → **+ New Resource → Database → PostgreSQL 16**.

- Name: `feedbot-db`
- Click **Deploy**
- Once running, copy the **internal connection URL** from the database's overview tab. It looks like:
  `postgres://feedbot:****@feedbot-db:5432/postgres`
- We'll convert it to async-style in step 4.

---

## 2. Create the API service

**+ New Resource → Public Repository**.

- Repository: `https://github.com/helderpgoncalves/feedbot`
- Branch: `main`
- Build pack: **Dockerfile**
- Dockerfile location: `packages/feedbot-api/Dockerfile`
- Base directory: `/`
- Click **Continue**.

### 2a. Domain & port

In the API service settings:

- **Domain**: `api.example.com` (split-domain) — or skip the public domain entirely (recommended; the SPA's Caddy is the only thing that needs to reach `:8000`, and it does so over the internal Docker network).
- **Port exposed**: `8000`
- Coolify will obtain a Let's Encrypt cert if you set a public domain.

If you skip the public domain on the API, the SPA's `FEEDBOT_API_UPSTREAM` (next step) points at the API's internal name (`feedbot-api:8000`) and the API stays unreachable from the internet — only the SPA touches it.

---

## 3. Create the web (SPA) service

**+ New Resource → Public Repository** again.

- Repository: `https://github.com/helderpgoncalves/feedbot`
- Branch: `main`
- Build pack: **Dockerfile**
- Dockerfile location: `apps/web/Dockerfile`
- Base directory: `/apps/web`
- Click **Continue**.

### 3a. Domain & port

- **Domain**: `app.example.com`
- **Port exposed**: `80`
- TLS via Let's Encrypt — Coolify handles this.

### 3b. Web env vars

The SPA reads runtime config from `/config.json`, which Caddy templates from env vars on every request. **You change these and `restart` — never rebuild.**

```env
# ─── API location (internal Docker network, no TLS needed) ────
FEEDBOT_API_UPSTREAM=http://feedbot-api:8000

# ─── Public-facing config baked into /config.json ─────────────
FEEDBOT_PUBLIC_URL=https://app.example.com
FEEDBOT_PRODUCT_NAME=Feedbot
FEEDBOT_DEPLOYMENT=self-host          # or "cloud" if you're running the hosted version
FEEDBOT_ALLOW_SIGNUP=false            # leave false unless you really want public signup
FEEDBOT_TELEGRAM_BOT_USERNAME=        # set in step 7 if you enable the bot

# ─── Optional: split-domain MCP URL ───────────────────────────
# Only set if your API has a public domain different from the SPA.
# Otherwise the SPA derives ${FEEDBOT_PUBLIC_URL}/mcp/ automatically.
# FEEDBOT_MCP_PUBLIC_URL=https://api.example.com/mcp/
```

---

## 4. API env vars

Generate two strong secrets locally:

```bash
python -c "import secrets; print('FEEDBOT_SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('FEEDBOT_BOT_TOKEN='  + secrets.token_urlsafe(32))"
```

In Coolify → **API service** → **Environment Variables**:

```env
# ─── Required ──────────────────────────────────────────────
FEEDBOT_BASE_URL=https://app.example.com
FEEDBOT_SECRET_KEY=<paste-generated>
FEEDBOT_BOT_TOKEN=<paste-generated>
DATABASE_URL=postgresql+asyncpg://feedbot:<password>@feedbot-db:5432/postgres

# ─── Email (mandatory in production) ───────────────────────
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USER=resend
SMTP_PASSWORD=<resend-api-key>
SMTP_FROM=feedbot@example.com

# ─── Telegram (set in step 7 if you enable the bot) ────────
TELEGRAM_BOT_TOKEN=
FEEDBOT_TELEGRAM_BOT_USERNAME=

# ─── Logs ──────────────────────────────────────────────────
FEEDBOT_LOG_LEVEL=INFO
```

> **`FEEDBOT_BASE_URL` is the public URL of the SPA**, not the API. The API uses it to build magic-link URLs that point at the SPA's `/magic` route. If you split domains, this stays `https://app.example.com` regardless of where the API lives.

> **The `DATABASE_URL` from Coolify's managed Postgres uses the sync `postgres://` scheme.** Replace it with `postgresql+asyncpg://` for Feedbot — the password and host stay the same.

> **`EMAIL_BACKEND=console` is refused for HTTPS deployments.** The app returns `503 Email delivery not configured` on `/v1/auth/login` until you set `EMAIL_BACKEND=smtp` + the SMTP_* vars. This is a feature, not a bug — it prevents you from accidentally locking out your users.

---

## 5. Connect the services

Both services need to be on the same Coolify project so the internal Docker network resolves `feedbot-api` and `feedbot-db` by name. If you created them in different projects, move them into one project from each service's **Settings → Project**.

You can verify the wiring before going further by opening Coolify's **Logs** on the API service and looking for:
- `Application startup complete.` — FastAPI boot OK.
- `EMAIL_BACKEND=console on a public HTTPS deployment` warning — only printed if SMTP isn't wired correctly. Fix env vars before continuing.

---

## 6. Deploy and run first-run setup

Click **Deploy** on both services. First builds take ~3 minutes (Python image + Node image for SPA). When health checks go green:

1. Open `https://app.example.com`.
2. The SPA hits `GET /v1/setup-status`, sees the empty database, and routes you to **`/setup`**.
3. Enter your owner email + workspace name → submit.
4. Magic link arrives in your inbox. Click → you land at `/projects` as the owner.
5. Go to **Team** → invite your colleagues with `admin` or `member` role.

> **No SMTP yet?** The `/v1/setup` response includes a `fallback_link` that the SPA renders as a one-click button — it's the same magic link, surfaced inline so you don't get locked out of your own instance during initial bootstrap. **Wire SMTP before inviting anyone else** or invites silently fail.

---

## 7. (Optional) Enable the Telegram bot

The bot serves every project via `chat_id` routing — **one bot for all projects**.

### 7a. Create the bot
- DM `@BotFather` → `/newbot` → save the token.
- `/setprivacy` → **Disable** (so it can read group messages).

### 7b. Add the credentials
In Coolify environment variables:

- On the **API** service: `TELEGRAM_BOT_TOKEN=123456:AA-...` and `FEEDBOT_TELEGRAM_BOT_USERNAME=your_bot_user_without_at`.
- On the **web** service: `FEEDBOT_TELEGRAM_BOT_USERNAME=your_bot_user_without_at` (so the dashboard can render the deep-link button).

### 7c. Activate the `bot` service

The bot is a **third Coolify resource** built from `packages/feedbot-bot/Dockerfile`:

- **+ New Resource → Public Repository → Dockerfile**
- Repository: `https://github.com/helderpgoncalves/feedbot`
- Dockerfile location: `packages/feedbot-bot/Dockerfile`
- **No domain, no exposed port** — the bot only talks to the API and to Telegram, both outbound.
- Env vars on the bot:
  ```env
  FEEDBOT_API_URL=http://feedbot-api:8000
  FEEDBOT_BOT_TOKEN=<same value as on the API>
  TELEGRAM_BOT_TOKEN=<same as 7b>
  ```
- Deploy.

### 7d. Onboard a chat

1. In the dashboard → open a project → **Telegram chats** card → **Generate invite**.
2. Click **Open in Telegram → Add to group** → pick a group → tap **Start**.
3. The bot replies confirming the link. Mentions in that group land in this project.

Repeat for any number of projects/groups. The same bot handles all of them.

---

## 8. Hook an MCP client (Claude Code, Cursor, Windsurf, …)

Two paths:

**Easy path (recommended).** Open a project in the dashboard → **Connect via MCP** card → copy the snippet for your client. The dashboard pre-fills your deployment's URL and a freshly issued API key.

**Manual path.**

```bash
# Claude Code (CLI)
claude mcp add --transport http feedbot https://app.example.com/mcp/ \
  --header "Authorization: Bearer fbk_live_..."
```

```json
// Claude Desktop / Cursor / Windsurf — paste into the relevant config file
{
  "mcpServers": {
    "feedbot": {
      "type": "http",
      "url": "https://app.example.com/mcp/",
      "headers": { "Authorization": "Bearer fbk_live_..." }
    }
  }
}
```

In your agent: *"What new bugs do we have?"* — done.

---

## Operational runbook

### Health & logs
- **API health check**: `GET /healthz` returns `{ok, email_backend, email_backend_unsafe_for_prod}`. Coolify polls this every 15s.
- **Web health check**: `GET /config.json` returns 200 with the runtime config — Caddy itself.
- **Application logs**: Coolify → service → Logs.
- **Magic link debugging**: when something goes wrong, `docker logs <api-container> | grep magic` shows the link being generated. In production this should never be the path users use — but it's a useful escape hatch.

### Backups
- Managed Postgres: enable Coolify's backup schedule on the database resource.
- Self-managed: run `pg_dump` from a sidecar with a cron schedule.

### Rotate secrets
- `FEEDBOT_SECRET_KEY`: rotating invalidates all sessions (everyone is logged out) **and** all encrypted LLM keys (the encryption key is derived from this). After rotating, every project owner has to re-enter their LLM provider key.
- `FEEDBOT_BOT_TOKEN`: rotate on **API and bot** simultaneously, then restart both. The bot can't ingest until both env vars match.
- API keys: from the project page in the dashboard → **API keys** card → **Revoke**. New keys come from the same card.

### Upgrades
Coolify auto-deploys on every push to `main` (toggle in service settings). Migrations run on `api` startup. To roll back, deploy the previous Git ref via the UI for both services together — never roll back the API to a version older than what the SPA was generated against.

### Common errors

| Symptom | Diagnose |
|---|---|
| SPA loads but `/v1/me` returns 404 / HTML | Caddy isn't proxying to the API. Check `FEEDBOT_API_UPSTREAM` on the web service points at the right internal name. |
| `/setup` wizard never shows up | Database isn't empty. Check via `psql` — if there's an unwanted owner from a botched first deploy, drop the `users` table and let `/setup` start over (only safe before you have real users). |
| `/v1/auth/login` returns 503 | `EMAIL_BACKEND` is not `smtp` while `FEEDBOT_BASE_URL` is HTTPS. Fix env vars on the API service. |
| Login goes through but no email arrives | Wrong SMTP credentials or sender domain not verified at provider. Check `docker logs <api>`. |
| Bot replies "this chat isn't connected" | The chat hasn't been onboarded via the dashboard's Generate-invite flow. |
| Members see no projects | They haven't been added to any project. Owner/admin → project → **Members** card → **Add member**. |
| MCP client says 401 | API key is revoked or wrong tenant. Re-issue from the project's **API keys** card. |

---

## Hardening checklist (production)

Before opening to non-admins:

- [ ] `FEEDBOT_BASE_URL` is `https://...` (and matches `FEEDBOT_PUBLIC_URL` on the web service).
- [ ] `EMAIL_BACKEND=smtp` with verified sender domain.
- [ ] Strong randomly-generated `FEEDBOT_SECRET_KEY` (≥48 url-safe chars).
- [ ] Strong randomly-generated `FEEDBOT_BOT_TOKEN` (≥32 url-safe chars), identical on API and bot services.
- [ ] Postgres backups enabled.
- [ ] API service has **no public domain** (or a separate one with its own TLS) — the SPA's Caddy reaches it via the internal network.
- [ ] `FEEDBOT_ALLOW_SIGNUP=false` unless you actually want public signup.
- [ ] `secrets-scan` GitHub Action passing on `main`.
- [ ] `dependabot` PRs reviewed and merged regularly.

The first owner is created via `/setup`. After that, the only way in is via an explicit invite from an admin — there's no public sign-up unless you flip `FEEDBOT_ALLOW_SIGNUP=true`.
