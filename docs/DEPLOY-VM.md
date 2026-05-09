---
title: Deploy on a plain VM
description: Run the full feedbot.dev stack on a single VM with one `docker compose up`. Marketing, cloud SaaS, and installer all from the same compose file.
---

# Deploy Feedbot to a plain VM

Cloud v1.0 ships everything in **one** `docker-compose.cloud.yml`:

- `feedbot.dev` — landing + docs (Astro + Starlight)
- `app.feedbot.dev` — cloud SaaS (SPA + API + Postgres + optional bot)
- `get.feedbot.dev` — installer one-liner (curl gets shell, browser
  gets HTML)

If you have a Linux VM with Docker and a public IP, this guide takes
you to a working stack in ~15 minutes.

---

## Prerequisites

- A VM with **Docker 24+** and **Docker Compose v2** (`docker compose
  version` works).
- Three DNS A-records pointing at the VM's IP:
  ```
  feedbot.dev       → <VM IP>
  app.feedbot.dev   → <VM IP>
  get.feedbot.dev   → <VM IP>
  ```
  Verify with `dig +short feedbot.dev app.feedbot.dev get.feedbot.dev`.
- A reverse proxy in front of the compose to terminate TLS — see
  [TLS](#tls) below for two zero-config options.

---

## 1. Clone the repo

```bash
git clone https://github.com/helderpgoncalves/feedbot.git feedbot
cd feedbot
```

---

## 2. Generate secrets and write `.env`

```bash
cat > .env <<EOF
FEEDBOT_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n')
FEEDBOT_BOT_TOKEN=$(openssl rand -base64 32 | tr -d '\n')
FEEDBOT_DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=\n')

FEEDBOT_MARKETING_HOST=feedbot.dev
FEEDBOT_APP_HOST=app.feedbot.dev
FEEDBOT_INSTALLER_HOST=get.feedbot.dev

FEEDBOT_BASE_URL=https://app.feedbot.dev
FEEDBOT_PUBLIC_URL=https://app.feedbot.dev

FEEDBOT_DEPLOYMENT=cloud
FEEDBOT_ALLOW_SIGNUP=true
FEEDBOT_BILLING_ENABLED=false
FEEDBOT_PRODUCT_NAME=Feedbot

EMAIL_BACKEND=console
FEEDBOT_VERSION=latest
EOF
chmod 600 .env
```

> Mark the file `chmod 600` so other VM users can't read your secrets.

---

## 3. Bring it up

```bash
docker compose -f docker-compose.cloud.yml --env-file .env up -d
```

First boot pulls `nginx:alpine`, `postgres:16-alpine`, the three
`ghcr.io/helderpgoncalves/feedbot-*` images for SPA + API + bot, and
builds `feedbot-marketing` + `feedbot-installer` locally from this repo
(~2 minutes). Subsequent restarts reuse the cache.

Verify the containers:

```bash
docker compose -f docker-compose.cloud.yml ps
```

Every service should show `Up`. The `web` and `spa` services have an
internal healthcheck — they show `(healthy)` once nginx is serving and
the API is answering.

---

## 4. TLS

The compose serves plain HTTP on `web:80`. **Don't expose port 80 to
the internet without a TLS terminator in front.** Pick one:

### Option A — Caddy (one container, automatic Let's Encrypt)

The lowest-friction path. Add this to a separate `docker-compose.tls.yml`:

```yaml
name: feedbot-tls
services:
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./Caddyfile.tls:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
volumes:
  caddy_data:
  caddy_config:
```

Then `Caddyfile.tls`:

```caddy
feedbot.dev, app.feedbot.dev, get.feedbot.dev {
    reverse_proxy 127.0.0.1:8080
}
```

Make `web:80` available on `127.0.0.1:8080` of the host by adding to
the compose `web` service:

```yaml
    ports:
      - "127.0.0.1:8080:80"
```

Then `docker compose -f docker-compose.tls.yml up -d`. Caddy issues
three Let's Encrypt certs, auto-renews them, and forwards `:443` →
nginx. Done.

### Option B — Cloudflare Tunnel (no public IP, no firewall to open)

Install [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/) on
the VM, run `cloudflared tunnel create feedbot`, point a CNAME at the
tunnel for each domain, configure the tunnel to forward HTTP traffic
to `localhost:8080` (same `web` service expose as Option A). TLS is
handled at Cloudflare's edge.

### Option C — nginx-proxy-manager / Traefik (UI-driven)

Both ship a UI for issuing Let's Encrypt certs against your three
domains and forwarding to `web:80` over the docker network. Pick one
if you already run it.

---

## 5. Smoke test

Once TLS is up:

```bash
curl -sf https://feedbot.dev/ | grep -o '<title>[^<]*</title>'
# >>> <title>Feedbot · Turn community chat into a product backlog</title>

curl -sf https://app.feedbot.dev/healthz
# >>> {"ok": true, ...}

curl -sf https://app.feedbot.dev/config.json | jq .
# >>> { "deployment": "cloud", "allowSignup": true, "billingEnabled": false, ... }

curl -sf https://get.feedbot.dev/ | head -2
# >>> #!/bin/sh
# >>> # shellcheck shell=sh
```

---

## 6. SMTP (so magic links actually arrive)

Magic-link sign-in needs working email. Add to `.env`:

```env
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASSWORD=re_<your Resend API key>
no-reply@feedbot.dev
```

`docker compose up -d` re-creates the api container; magic links now
arrive in inboxes instead of `docker compose logs api`.

> The sender domain (`feedbot.dev`) needs SPF + DKIM + DMARC records
> in DNS. Resend's onboarding walks you through them; ~5 min.

---

## 7. Telegram bot (opt-in)

Set `FEEDBOT_TELEGRAM_BOT_TOKEN` from @BotFather in `.env`, then:

```bash
docker compose -f docker-compose.cloud.yml --env-file .env --profile bot up -d
```

The `bot` service starts and begins polling Telegram. Add it to a
group, redeem the link from the dashboard, post a message, watch the
feedback land in the SPA.

---

## 8. Updates

```bash
git pull
docker compose -f docker-compose.cloud.yml --env-file .env pull
docker compose -f docker-compose.cloud.yml --env-file .env up -d
```

`pull` refreshes the registry-hosted images; `up -d` rebuilds the
local marketing + installer images from the new commit. Coolify
operators can ignore this — the platform handles it on git push.

---

## 9. Backups

Add a cron entry on the host:

```cron
0 3 * * * cd /opt/feedbot && docker compose -f docker-compose.cloud.yml exec -T db pg_dump -U feedbot -Fc feedbot > /var/backups/feedbot-$(date +\%Y\%m\%dT\%H\%M\%SZ).dump
```

**Test the restore once before you need it.** See
[DEPLOY-COOLIFY.md §8.4](./DEPLOY-COOLIFY.md#84-restore-drill--the-critical-bit).

---

## Troubleshooting

**One of the three domains 404s.** Check that DNS for that FQDN is
actually pointing at this VM (`dig +short <fqdn>`) and that you set
`FEEDBOT_MARKETING_HOST` / `FEEDBOT_APP_HOST` /
`FEEDBOT_INSTALLER_HOST` to match in `.env`. The nginx `web` service
returns 404 for unrecognised `Host:` headers.

**`docker compose build` fails on `marketing`.** Make sure you're on
the repo root; the build context is `./apps/marketing`. The
installer's context is the repo root because its `build.sh` reads
`install.sh` from there.

**Magic links never arrive.** `EMAIL_BACKEND=console` (the default)
prints them to `docker compose logs api`. Set `EMAIL_BACKEND=smtp` +
SMTP creds to actually deliver.

**`get.feedbot.dev` shows the HTML page when piped through curl.** The
nginx in `apps/installer-host/Dockerfile` rewrites by User-Agent. Make
sure your TLS terminator (Caddy/Cloudflare/Traefik) **forwards the
User-Agent header** verbatim — most do by default.
