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

Cloud mode hides the Settings → Email UI. Set SMTP via Coolify env vars:

```env
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASSWORD=<your provider api key>
[email protected]
```

Save → Coolify recreates the api container → magic links work.

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

```bash
# Cloud SaaS
curl -sf https://app.feedbot.dev/healthz | jq
curl -sf https://app.feedbot.dev/config.json | jq

# Marketing
curl -sf https://feedbot.dev/ | head

# Installer
curl -sf https://get.feedbot.dev/ | head -10   # should be the install.sh shebang
```

You can now:

- Open `https://feedbot.dev` and read the docs.
- Open `https://app.feedbot.dev` to use the cloud SaaS.
- Tell anyone wanting to self-host: `curl -fsSL https://get.feedbot.dev | sh`.

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
- For multi-tenant + billing, set `FEEDBOT_BILLING_ENABLED=true` (UI placeholder
  for v0; billing implementation lands in a follow-up release).
