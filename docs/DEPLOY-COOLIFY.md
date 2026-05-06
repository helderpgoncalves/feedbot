# Deploy Feedbot to Coolify

Step-by-step guide to running Feedbot on a [Coolify](https://coolify.io/) instance with TLS, automatic deploys, and a managed Postgres. Estimated time: **20 minutes**.

---

## What you'll end up with

```
                       https://feedbot.your-domain.com
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────┐
   │                Coolify (Caddy/Traefik + Docker)          │
   │                                                          │
   │   ┌────────────────────┐         ┌────────────────────┐  │
   │   │  api  (FastAPI)    │ ◄─────► │  postgres (managed)│  │
   │   │  :8000             │         │                    │  │
   │   └────────────────────┘         └────────────────────┘  │
   │                                                          │
   │   ┌────────────────────┐ (optional, opt-in via profile)  │
   │   │  bot  (Telegram)   │                                 │
   │   └────────────────────┘                                 │
   └──────────────────────────────────────────────────────────┘
```

---

## Prerequisites

- Coolify v4+ self-hosted **or** Coolify Cloud.
- A domain pointing at your server (e.g. `feedbot.example.com → A record → server IP`).
- An SMTP provider (Resend, Postmark, SES, Brevo — any). Without one, magic-link login is disabled in production.
- (Optional) A Telegram bot token from `@BotFather`.

---

## 1. Create the Postgres database

In Coolify → **+ New Resource → Database → PostgreSQL 16**.

- Name: `feedbot-db`
- Click **Deploy**
- Once running, copy the **internal connection URL** from the database's overview tab. It looks like:
  `postgres://feedbot:****@feedbot-db:5432/postgres`
- We'll convert it to async-style in step 3.

---

## 2. Create the API as a Docker Compose application

**+ New Resource → Public Repository**.

- Repository: `https://github.com/helderpgoncalves/feedbot`
- Branch: `main`
- Build pack: **Docker Compose**
- Compose file: `docker-compose.yml`
- Click **Continue**.

Coolify will parse the compose file and offer the services. The `bot` service is behind a profile, so it won't be built or started yet. The `db` service from the compose file **will** be ignored (we use the managed one instead) — see step 4.

### 2a. Domain & port

In the `api` service settings:
- **Domain**: `feedbot.example.com`
- **Port exposed**: `8000`
- Coolify will obtain a Let's Encrypt cert and front the service automatically.

---

## 3. Environment variables

Generate two strong secrets locally:

```bash
python -c "import secrets; print('FEEDBOT_SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('FEEDBOT_BOT_TOKEN='  + secrets.token_urlsafe(32))"
```

In Coolify → application → **Environment Variables**, paste:

```env
# ─── Required ──────────────────────────────────────────────
FEEDBOT_BASE_URL=https://feedbot.example.com
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

# ─── Telegram (set later if you want the bot) ──────────────
TELEGRAM_BOT_TOKEN=
FEEDBOT_TELEGRAM_BOT_USERNAME=

# ─── Logs ──────────────────────────────────────────────────
FEEDBOT_LOG_LEVEL=INFO
```

> **The `DATABASE_URL` from Coolify's managed Postgres uses the sync `postgres://` scheme.** Replace it with `postgresql+asyncpg://` for Feedbot — the password and host stay the same.

> **`EMAIL_BACKEND=console` is refused for HTTPS deployments.** The app returns `503 Email delivery not configured` on `/login` until you set `EMAIL_BACKEND=smtp` + the SMTP_* vars. This is a feature, not a bug — it prevents you from accidentally locking out your users.

---

## 4. Disable the in-compose `db` service

Two options:

**Option A — fork and edit the compose file** *(recommended)*: keep your fork private and remove the `db:` service plus the `depends_on: db` line under `api:`. This is the cleanest path.

**Option B — keep the in-compose db**: skip step 1 (don't create the managed Postgres) and let the compose file create one inside the same stack. You lose Coolify's automated backups; bring your own `pg_dump` schedule.

If you went with **A**, set `DATABASE_URL` to the managed DB URL (step 3). If **B**, set it to `postgresql+asyncpg://feedbot:feedbot@db:5432/feedbot` and add a regular Postgres backup workflow.

---

## 5. Deploy

Click **Deploy**. First build takes ~2 minutes (Python image + dependencies). When the health check goes green:

1. Open `https://feedbot.example.com` → **/setup** loads automatically (database is empty).
2. Enter your owner email + workspace name → submit.
3. Magic link arrives in your inbox. Click → you land in `/app` as the owner.
4. Go to **Team** → invite your colleagues with `admin` or `member` role.

---

## 6. (Optional) Enable the Telegram bot

The bot serves every project via `chat_id` routing — **one bot for all projects**.

### 6a. Create the bot
- DM `@BotFather` → `/newbot` → save the token.
- `/setprivacy` → **Disable** (so it can read group messages).

### 6b. Add the credentials
In Coolify environment variables, set:
- `TELEGRAM_BOT_TOKEN=123456:AA-...`
- `FEEDBOT_TELEGRAM_BOT_USERNAME=your_bot_user_without_at`

### 6c. Activate the `bot` service

The compose file ships the `bot` behind a Coolify-friendly profile so it doesn't crash on first deploy. To activate:

**Easiest**: in your fork, remove the `profiles: ["bot"]` line under the `bot:` service, push → Coolify redeploys with the bot. The bot needs no external port and no domain.

### 6d. Onboard a chat
1. In the dashboard → project page → **Generate Telegram invite**.
2. Click **Open Telegram → Add to group** → pick a group → tap **Start**.
3. The bot replies confirming the link. Mentions in that group land in this project.

Repeat for any number of projects/groups. The same bot handles all of them.

---

## 7. Hook Claude Code via MCP

On your laptop:

```bash
pip install -e packages/feedbot-mcp   # or pip install feedbot-mcp once published

claude mcp add feedbot \
  --transport stdio \
  --env FEEDBOT_API_URL=https://feedbot.example.com \
  --env FEEDBOT_API_KEY=fbk_live_...   # issue from the project page
  -- feedbot-mcp
```

Inside Claude Code: *"What new bugs do we have?"* — done.

---

## Operational runbook

### Health & logs
- **Health check**: `GET /healthz` returns `{ok, email_backend, email_backend_unsafe_for_prod}`. Coolify polls this every 15s.
- **Application logs**: Coolify → application → Logs.
- **Magic link debugging**: when something goes wrong, `docker logs <api-container> | grep magic` shows the link being generated. In production this should never be the path users use — but it's a useful escape hatch.

### Backups
- Managed Postgres: enable Coolify's backup schedule on the database resource.
- Self-managed: run `pg_dump` from a sidecar with a cron schedule.

### Rotate secrets
- `FEEDBOT_SECRET_KEY`: rotating invalidates all sessions (everyone is logged out). Magic-link tokens at rest are unaffected (they're hashed with Argon2, not signed with this key).
- `FEEDBOT_BOT_TOKEN`: rotate → restart bot. The bot can't ingest until both env vars match.
- API keys: from the project page in the dashboard. The old key keeps working until you press "Revoke" (planned UI; for now: `UPDATE api_keys SET revoked_at = now() WHERE prefix = 'fbk_live_xxxxxxxx';`).

### Upgrades
Coolify auto-deploys on every push to `main` (toggle in app settings). Migrations run on `api` startup. To roll back, deploy the previous Git ref via the UI.

### Common errors

| Symptom | Diagnose |
|---|---|
| `/setup` 410 Gone | Bootstrap already complete. Use `/login` instead. |
| `/login` returns 503 | `EMAIL_BACKEND` is not `smtp` while serving HTTPS. Fix env vars. |
| Login goes through but no email arrives | Wrong SMTP credentials or sender domain not verified at provider. Check `docker logs api`. |
| Bot replies "this chat isn't connected" | The chat hasn't been onboarded via the dashboard's Generate-invite flow. |
| Members see no projects | They haven't been added to any project. Owner/admin → project → Members → Add member. |

---

## Hardening checklist (production)

Before opening to non-admins:

- [ ] `FEEDBOT_BASE_URL` is `https://...`.
- [ ] `EMAIL_BACKEND=smtp` with verified sender domain.
- [ ] Strong randomly-generated `FEEDBOT_SECRET_KEY` (≥48 url-safe chars).
- [ ] Strong randomly-generated `FEEDBOT_BOT_TOKEN` (≥32 url-safe chars).
- [ ] Postgres backups enabled.
- [ ] `/healthz` exposed *only* on the public domain, not on a separate port.
- [ ] `secrets-scan` GitHub Action passing on `main`.
- [ ] `dependabot` PRs reviewed and merged regularly.

The first owner is created via `/setup`. After that, the only way in is via an explicit invite from an admin — there's no public sign-up.
