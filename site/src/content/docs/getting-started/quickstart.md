---
title: Quickstart
description: Run Feedbot locally with Docker in five minutes — owner setup, first project, first API key.
---

Five minutes from `git clone` to a running dashboard. No SMTP, no Telegram, no Claude Code required for this step — those layer on top once the basics work.

## Prerequisites

- Docker Desktop running.
- Free ports `8000` (API) and `5432` (Postgres).
- Optional: `jq` for prettier curl output (`brew install jq`).

## 1. Clone + secrets

```bash
git clone https://github.com/helderpgoncalves/feedbot.git
cd feedbot
cp .env.example .env

# Generate strong dev secrets — paste each line into .env
python -c "import secrets; print('FEEDBOT_SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('FEEDBOT_BOT_TOKEN='  + secrets.token_urlsafe(32))"
```

Leave `TELEGRAM_BOT_TOKEN` and `FEEDBOT_TELEGRAM_BOT_USERNAME` empty for now. `EMAIL_BACKEND=console` is fine for local dev — magic links print to the API logs.

## 2. Boot the API + database

```bash
docker compose up --build -d db api
docker compose logs -f api
```

Wait for `Uvicorn running on http://0.0.0.0:8000`. Migrations run automatically on startup. `Ctrl+C` to leave the log tail.

## 3. First-run setup

Open <http://localhost:8000>. Because the database is empty, the app redirects you to `/setup`.

1. Enter your email + workspace name → submit.
2. The magic link prints to the API logs:
   ```bash
   docker compose logs api | grep "magic link"
   ```
3. Open the URL → you land in `/app` as the **owner**.

:::tip
The `/setup` route only works while the `users` table is empty. Once the owner is created it returns `410 Gone`. From here on, the only way new users get in is via an invite.
:::

## 4. Create a project + API key

In `/app`:

1. **New project** form → slug `demo`, name "Demo Project" → Create.
2. Click into the project → **Issue key** with label *"Claude Code on laptop"* → copy the `fbk_live_…` value. (You won't see it again.)

## What's next

- Smoke-test the API with curl → see [End-to-end test](/getting-started/end-to-end/).
- Wire up Claude Code → [MCP tools reference](/reference/mcp-tools/).
- Turn on auto-triage → [LLM providers](/reference/llm-providers/).
- Go to production → [Coolify deploy](/deploy/coolify/).
