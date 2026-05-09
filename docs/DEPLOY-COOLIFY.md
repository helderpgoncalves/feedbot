---
title: Deploy on Coolify
description: Run Feedbot on Coolify with TLS, automatic deploys, and a managed Postgres. Three Coolify Applications cover the full feedbot.dev stack — cloud SaaS, marketing site, and the install one-liner.
---

# Deploy Feedbot to Coolify

This guide walks you through deploying the **full feedbot.dev stack** on a single
[Coolify](https://coolify.io/) instance: the cloud SaaS at `app.feedbot.dev`, the
marketing site + docs at `feedbot.dev`, and the install one-liner endpoint at
`get.feedbot.dev`. Estimated time: **35 minutes** end-to-end.

Each subdomain is a separate Coolify **Application** so you can redeploy any of
them independently.

---

## What you'll end up with

```
   ┌──────────────────────── feedbot.dev ────────────────────────┐
   │                                                              │
   │     feedbot.dev          app.feedbot.dev      get.feedbot.dev│
   │     ────────────         ─────────────────    ──────────────│
   │     Marketing +          Cloud SaaS           install.sh    │
   │     docs (Astro)         (api + web + db)     served plain  │
   │                                                              │
   │       ▼                       ▼                    ▼         │
   │   ┌──────────────────────────────────────────────────────┐   │
   │   │     Coolify Traefik (one TLS edge for all three)     │   │
   │   └──────────────────────────────────────────────────────┘   │
   └──────────────────────────────────────────────────────────────┘
```

Three Coolify Applications:

| Application | Source | Compose / type | Domain |
|---|---|---|---|
| `feedbot-app` | This repo (`feedbot-mono`) | Docker Compose: `docker-compose.cloud.yml` | `app.feedbot.dev` |
| `feedbot-marketing` | This repo, `apps/marketing/` | Static Site (Astro build) | `feedbot.dev` |
| `feedbot-installer` | Same repo or a separate one | Static Site (serves `install.sh`) | `get.feedbot.dev` |

---

## Prerequisites

- A Coolify v4+ instance running on a Linux server with a public IP.
- Three DNS A-records pointing at that server's IP:
  - `feedbot.dev` → server IP
  - `app.feedbot.dev` → server IP
  - `get.feedbot.dev` → server IP
- DNS must be propagated before Let's Encrypt can issue certs. Verify with
  `dig +short feedbot.dev app.feedbot.dev get.feedbot.dev`.

---

## 1. Connect this repo as a GitHub source

In Coolify → **Sources → New → GitHub App** → install the Coolify GitHub App on
the `feedbot` repo. Coolify can now `git pull` on push.

---

## 2. Application 1 — Cloud SaaS (`app.feedbot.dev`)

This is the live app: SPA + JSON API + Postgres. Deploys from
`docker-compose.cloud.yml` in the repo root.

**Create:**

1. **+ New Resource → Application → Public Repository / GitHub App**.
2. Repository: `feedbot-mono` · Branch: `main`.
3. **Build Pack: Docker Compose**.
4. **Compose Path:** `docker-compose.cloud.yml`.
5. **Domain:** `https://app.feedbot.dev`.
6. **Environment variables:** copy-paste the block below into the Application's
   Environment tab. Generate the three secrets first:
   ```bash
   # On any machine with openssl:
   openssl rand -base64 48 | tr -d '\n'   # → FEEDBOT_SECRET_KEY
   openssl rand -base64 32 | tr -d '\n'   # → FEEDBOT_BOT_TOKEN
   openssl rand -base64 24 | tr -d '/+='  # → FEEDBOT_DB_PASSWORD
   ```

   Then in Coolify Environment → **Add Bulk**:
   ```env
   FEEDBOT_PUBLIC_DOMAIN=app.feedbot.dev
   FEEDBOT_BASE_URL=https://app.feedbot.dev
   FEEDBOT_PUBLIC_URL=https://app.feedbot.dev
   FEEDBOT_SECRET_KEY=<paste from openssl>
   FEEDBOT_BOT_TOKEN=<paste from openssl>
   FEEDBOT_DB_PASSWORD=<paste from openssl>
   FEEDBOT_VERSION=latest
   FEEDBOT_DEPLOYMENT=cloud
   FEEDBOT_ALLOW_SIGNUP=true
   FEEDBOT_BILLING_ENABLED=false
   FEEDBOT_PRODUCT_NAME=Feedbot
   EMAIL_BACKEND=console
   ```

   > Mark `FEEDBOT_SECRET_KEY`, `FEEDBOT_BOT_TOKEN`, `FEEDBOT_DB_PASSWORD` as
   > **Secret** in Coolify (the eye icon) so they don't show in the UI later.

7. **Deploy**. First deploy takes ~3 minutes (image pulls + first compose up).
   Coolify's Traefik issues the Let's Encrypt cert automatically.

**Verify:**
- `https://app.feedbot.dev/healthz` returns `{"ok": true, ...}`
- `https://app.feedbot.dev/config.json` returns the runtime config
- `https://app.feedbot.dev/` loads the SPA

**Configure SMTP (post-deploy):**

Cloud mode hides the Settings → Email UI. Set SMTP via Coolify env vars
(example uses [Resend](https://resend.com) — same shape works for
Postmark, SES, Brevo, Sendgrid, Fastmail SMTP, etc.):

```env
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASSWORD=re_<your Resend API key>
[email protected]
```

Save → Coolify recreates the api container → magic links work.

> Before this works, the Resend account needs to verify the domain
> (`feedbot.dev`) by adding 3 DNS records in Cloudflare (MX, SPF, DKIM
> on the `send.feedbot.dev` subdomain). Resend's UI walks you through
> this; total setup ~5 minutes.

---

## 3. Application 2 — Marketing + docs (`feedbot.dev`)

The marketing site lives in `apps/marketing/` (Astro + Starlight). Coolify
builds it as a static site.

1. **+ New Resource → Application → GitHub App**, same repo, branch `main`.
2. **Build Pack: Static**.
3. **Base directory:** `apps/marketing`.
4. **Install command:** `pnpm install`.
5. **Build command:** `pnpm build`.
6. **Publish directory:** `apps/marketing/dist`.
7. **Domain:** `https://feedbot.dev`.
8. Deploy.

The marketing build is pure static HTML so no env vars are required.

---

## 4. Application 3 — Install one-liner (`get.feedbot.dev`)

`get.feedbot.dev` serves `install.sh` so
`curl -fsSL https://get.feedbot.dev | sh` works. The simplest setup is a
Coolify Static Site driven by the `apps/installer-host/` directory which
copies the canonical `install.sh` from the repo root on every build.

1. **+ New Resource → Application → GitHub App**, same repo, branch `main`.
2. **Build Pack: Static**.
3. **Base directory:** `apps/installer-host`.
4. **Install command:** *(leave empty — no dependencies)*.
5. **Build command:** `sh build.sh`.
6. **Publish directory:** `apps/installer-host/dist`.
7. **Domain:** `https://get.feedbot.dev`.
8. **Custom Caddy config** (Coolify → Application → Advanced → Caddyfile):

   ```caddy
   handle / {
       rewrite * /install.sh
       header Content-Type "text/plain; charset=utf-8"
   }
   handle /install.sh {
       header Content-Type "text/plain; charset=utf-8"
   }
   handle {
       try_files {path} {path}/ /index.html
   }
   ```

   The first block makes `curl https://get.feedbot.dev | sh` return the
   installer at `/`. The second handles direct requests to `/install.sh`.
   The fallback handles `/index.html` (browser visitors).

9. Deploy.

After Coolify finishes:

- `curl -fsSL https://get.feedbot.dev | sh` runs the installer.
- `curl https://get.feedbot.dev/install.sh` returns the same content.
- Opening `https://get.feedbot.dev/index.html` in a browser shows a
  human-friendly explainer.

---

## 5. Auto-deploy on push

In each Application → **Settings → Webhook**:

1. Enable **Auto Deploy on Push**.
2. Coolify shows a webhook URL — Coolify's GitHub App registers it
   automatically when you connected the source in step 1.

Every push to `main` now redeploys whichever Application's source files
changed.

---

## 6. Backups (Postgres)

The `db` service in `docker-compose.cloud.yml` uses a Coolify-managed Docker
volume (`db_data`). To take a backup:

```bash
# From your laptop, via the Coolify SSH terminal for feedbot-app:
docker compose exec -T db pg_dump -U feedbot -Fc feedbot > backup.dump
```

The shipped CLI does the same thing for self-hosters via `feedbot backup`. To
hook this into a schedule, use Coolify → **Application → Scheduled Tasks**:

- Cron: `0 3 * * *` (3 AM UTC nightly)
- Command: `docker compose exec -T db pg_dump -U feedbot -Fc feedbot > /data/backups/feedbot-$(date +%Y%m%dT%H%M%SZ).dump`

---

## 7. Verify end-to-end

### 7.1 Static smoke

```bash
# Cloud SaaS
curl -sf https://app.feedbot.dev/healthz | jq
curl -sf https://app.feedbot.dev/config.json | jq
# Expected (free closed-beta): allowSignup=true, billingEnabled=false,
# deployment="cloud".

# Marketing
curl -sf https://feedbot.dev/ | head

# Installer
curl -sf https://get.feedbot.dev/ | head -10   # should be the install.sh shebang
```

### 7.2 Cloud signup smoke (manual, ~5 min)

The full happy path before announcing closed-beta:

1. Open `https://app.feedbot.dev` in a private window  >>>  redirected to `/signup`
   (because the DB is empty and `allowSignup=true`).
2. Submit your email + workspace name  >>>  "check your email" card.
3. Open the magic-link from the inbox  >>>  lands at `/projects` as the new
   tenant's owner. Workspace name is the value you typed.
4. Create your first project  >>>  no 402 (billing disabled in C1).
5. Generate an API key, copy the MCP URL, wire it into Claude Code  >>>
   one-tool ping should succeed.
6. Add the Telegram bot to a group, redeem the link from the dashboard,
   send a test message  >>>  feedback appears in the dashboard, reply
   from the dashboard surfaces in the chat.
7. Sign out  >>>  next visit lands on `/login`, sign-up link visible
   (because `cfg.allowSignup === true`).

### 7.3 Hide from search engines while in closed-beta

Until you're ready for a public launch, ship a `noindex` meta tag on the
SPA. The simplest place: edit `apps/web/index.html` and add
`<meta name="robots" content="noindex">` inside `<head>`. Remove this
line as part of the C5 launch checklist.

You can now:

- Open `https://feedbot.dev` and read the docs.
- Open `https://app.feedbot.dev` to use the cloud SaaS (closed-beta).
- Tell anyone wanting to self-host: `curl -fsSL https://get.feedbot.dev | sh`.

---

## 8. Operational hardening (recommended for paying customers)

Closed-beta works on `docker compose logs` + manual checks. Before
announcing public commercial GA, set up the four basics below.

### 8.1 Error tracking — Sentry

Backend + SPA. Add a Sentry project, paste the DSN as
`FEEDBOT_SENTRY_DSN` in Coolify, restart. The `feedbot_api` boot wires
Sentry's FastAPI integration when this var is set; the SPA reads
`sentryDsn` from `/config.json` and initialises lazy after first paint
to avoid blocking TTI. Self-host leaves the var unset → Sentry never
loads.

### 8.2 Structured logs — Loki / Better Stack / similar

`docker compose logs feedbot-api` is enough for one container, but as
soon as you scale workers or add the bot service, ship logs to a
managed sink. Coolify supports Vector or Promtail side-cars; configure
either to forward `stdout` from `feedbot-app` to your sink. Search by
`request_id` (the API tags every log line) when reproducing customer
reports.

### 8.3 Status page

Most install: a free **Better Stack** monitor pinging
`https://app.feedbot.dev/healthz` every 30s with a public status page
at `status.feedbot.dev`. Add it to the marketing site footer (`apps/marketing/src/pages/index.astro`)
and link it from any incident-response tooling.

### 8.4 Restore drill — the critical bit

Backups exist (step 6.1). **A backup you've never restored is just a
file**. Once before public launch, exercise the full recipe:

```bash
# On a fresh disposable host:
ssh staging
docker compose -f docker-compose.cloud.yml up -d db
docker compose exec -T db pg_restore -U feedbot -d feedbot --clean --no-owner < /data/backups/<latest>.dump
docker compose -f docker-compose.cloud.yml up -d
curl -sf https://staging.feedbot.dev/healthz | jq
```

Document the exact commands you used in `docs/RESTORE-RUNBOOK.md` (a
template is included in the repo). When a real incident hits at 3 AM,
"copy from runbook" beats "remember the syntax".

### 8.5 On-call rotation (optional, useful past 10-20 paying customers)

Until then, a Slack channel + a "best-effort, EU business hours" SLA in
the marketing site is honest and sufficient. Once on-call is stood up,
update [Terms of Service](/legal/terms/) §6 and the marketing site to
match.

---

## Troubleshooting

**TLS cert isn't issuing.** Check Coolify → Application → Logs. Most common
cause is DNS not yet propagated; Let's Encrypt needs your domain to resolve to
the Coolify server. Re-trigger the cert issuance via the Application's
**Domains** panel.

**`/api/*` returns 404.** The `feedbot-api` Traefik router only matches paths
starting with `/api`, `/mcp`, or `/healthz`. Anything else hits `feedbot-web`
which serves the SPA. Curl `/api/healthz` (note: that's the API at
`/api/healthz`, distinct from the top-level `/healthz`) to validate routing.

**`docker compose exec db pg_dump` fails with "role 'feedbot' does not exist".**
First-time deploys need the api container to run alembic migrations to
bootstrap the schema. Check `feedbot-app` Application logs for
`alembic upgrade head` output.

**The SPA's `/config.json` shows wrong publicUrl.** It's templated by the web
container at boot from `FEEDBOT_PUBLIC_URL`. Update the env var in Coolify and
redeploy.

---

## Next steps

- Wire up SMTP via the env-var block in step 2.
- Connect a Telegram bot: set `TELEGRAM_BOT_TOKEN` env var, then enable the
  `bot` profile in Coolify → Application → Compose Profiles.
- For multi-tenant + billing, set `FEEDBOT_BILLING_ENABLED=true` plus the
  Stripe env vars (`FEEDBOT_STRIPE_SECRET_KEY`, `FEEDBOT_STRIPE_WEBHOOK_SECRET`,
  `FEEDBOT_STRIPE_PRICE_PRO`, `FEEDBOT_STRIPE_PRICE_TEAM`). Configure a
  Stripe webhook endpoint pointing at
  `https://app.feedbot.dev/v1/internal/stripe-webhook` and subscribe to
  `customer.subscription.*` and `invoice.payment_*` events.
- Walk through §8 (Sentry + structured logs + status page + restore drill)
  before announcing commercial GA.
