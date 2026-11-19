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

## Upgrading Postgres to a new major version

The bundled database is pinned to `postgres:16-alpine`. Do **not** just bump the image tag to a
new major (17, 18, …): the data directory on the `db` volume is tied to the major that created it,
and the new server refuses to start on it. Dependabot ignores Postgres majors for this reason.

A major upgrade is a planned operation:

1. Take a dump with the *old* image still running:
   `docker compose exec db pg_dump -U feedbot -Fc feedbot > feedbot-$(date +%F).dump`
2. Stop the stack and move the old volume aside (keep it until the upgrade is verified).
3. Bump the `db` image in `docker-compose.yml` (and `install.sh` / `docker-compose.cloud.yml`),
   start only `db` so it initialises an empty data directory.
4. Restore: `docker compose exec -T db pg_restore -U feedbot -d feedbot --no-owner < feedbot-<date>.dump`
5. Start the rest of the stack (`api` runs `alembic upgrade head`) and smoke-test before dropping the old volume.

`pg_upgrade` (e.g. the `tianon/postgres-upgrade` images) is faster for large databases but needs both
binaries side by side; dump/restore is the simpler default at Feedbot's scale.
