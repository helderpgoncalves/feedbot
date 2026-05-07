---
title: Generic deployment
description: Deploy Feedbot on any Linux host with Docker — bring your own Postgres and reverse proxy. Reference for non-Coolify hosts.
---

# Deployment

## Self-hosted (Docker)

```bash
cp .env.example .env
# Required: FEEDBOT_SECRET_KEY (long random), TELEGRAM_BOT_TOKEN
docker compose up --build -d
```

Services:

- `db` — Postgres 16
- `api` — FastAPI on `:8000`. Runs migrations on start.
- `bot` — Telegram bot. Needs `FEEDBOT_API_KEY` set in `.env` (issue one from the dashboard first, then restart this service).

## Hosted (single VPS, single domain)

1. Point `feedbot.example.com` at the host.
2. Front the API with Caddy / Traefik for TLS.
3. Set `FEEDBOT_BASE_URL=https://feedbot.example.com` so magic-link emails contain the public URL.
4. Use a real SMTP backend (set `EMAIL_BACKEND=smtp` + SMTP credentials).

## Telegram bot setup

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → save the token.
2. Disable privacy mode: `/setprivacy` → `Disable` (so the bot can see all group messages).
3. Add the bot to your group as admin.
4. Set `TELEGRAM_BOT_TOKEN` and `FEEDBOT_API_KEY` (project-scoped) in `.env` and start the `bot` service.

## Backups

`pg_dump` on a schedule. Sessions are signed cookies; nothing else lives outside Postgres.
