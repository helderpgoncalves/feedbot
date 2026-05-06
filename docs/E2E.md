# End-to-end test (Docker)

Walks through the whole loop locally — without needing SMTP, Telegram, or a Claude Code install — and then layers Telegram + MCP on top once the basics work.

## 0. Prereqs
- Docker Desktop running
- Free port `8000` (API) and `5432` (Postgres)
- (Optional) `jq` for prettier curl output: `brew install jq`

## 1. Set up `.env`

```bash
cd feedbot
cp .env.example .env

# Generate strong dev secrets
python -c "import secrets; print('FEEDBOT_SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('FEEDBOT_BOT_TOKEN='  + secrets.token_urlsafe(32))"
```

Paste those two lines into `.env`, replacing the placeholders. Leave `TELEGRAM_BOT_TOKEN` and `FEEDBOT_TELEGRAM_BOT_USERNAME` empty for now.

## 2. Build + start db + api

```bash
docker compose up --build -d db api
docker compose logs -f api
```

Wait for `Uvicorn running on http://0.0.0.0:8000`. Migrations run automatically on startup. Ctrl+C to leave the log tail.

## 3. Seed a project + API key

```bash
docker compose exec api python scripts/seed.py \
  --email you@example.com --slug demo --name "Demo Project"
```

The output ends with `api key   fbk_live_…verylongstring`. **Copy it.**

## 4. Smoke test the API with curl

```bash
KEY="fbk_live_..."   # paste from step 3

# Create a feedback (the same shape the bot uses)
curl -s -X POST http://localhost:8000/v1/feedbacks \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"Export crashes on iOS","body":"Hangs >100 rows.","type":"bug","severity":"high","author_platform":"web","author_id":"u-123","author_name":"Maria"}' | jq

# List, stats
curl -s http://localhost:8000/v1/feedbacks -H "Authorization: Bearer $KEY" | jq
curl -s http://localhost:8000/v1/stats     -H "Authorization: Bearer $KEY" | jq

# Patch
FB=$(curl -s http://localhost:8000/v1/feedbacks -H "Authorization: Bearer $KEY" | jq -r '.[0].id')
curl -s -X PATCH http://localhost:8000/v1/feedbacks/$FB \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"status":"in_progress","note":"investigating"}' | jq
```

## 5. Visit the dashboard

Open <http://localhost:8000> → **Sign in** → enter `you@example.com`.

The magic link prints to the API logs:

```bash
docker compose logs api | grep "magic link"
```

Open the URL → you land on `/app` with the Demo Project. Click into it and you'll see the row from step 4, the API key (only the prefix), the connected-chats panel, and the stats counts.

## 6. Hook up Claude Code via MCP (host-side)

```bash
pip install -e packages/feedbot-mcp

claude mcp add feedbot \
  --transport stdio \
  --env FEEDBOT_API_URL=http://localhost:8000 \
  --env FEEDBOT_API_KEY=$KEY \
  -- feedbot-mcp

claude mcp list   # should show feedbot
```

Inside Claude Code: *"What feedback is open in the demo project?"* — Claude calls `list_feedbacks` and prints the row.

> Reference: <https://code.claude.com/docs/en/mcp>. The order matters: all flags before the server name, then `--`.

## 7. Telegram (one bot, N projects)

This step needs a real Telegram bot token. The bot is **global** — the same bot serves every project; routing is decided server-side via `chat_id → project` links.

### 7a. Create the bot
1. DM [@BotFather](https://t.me/BotFather) → `/newbot` → save the token.
2. `/setprivacy` → **Disable** (so the bot can read group messages).
3. `/setcommands` → paste:
   ```
   start - Onboard or show help
   ```

### 7b. Configure `.env`

Add:

```env
TELEGRAM_BOT_TOKEN=123456:AA-Your-Real-Token
FEEDBOT_TELEGRAM_BOT_USERNAME=your_bot_user_without_at
```

(`FEEDBOT_BOT_TOKEN` was already set in step 1.)

### 7c. Start the bot service

```bash
docker compose --profile bot up -d --build bot
docker compose logs -f bot
```

### 7d. Connect a Telegram group to a project

1. In the dashboard → project page → **Generate Telegram invite**.
2. Click **Open Telegram → Add to group**. Telegram opens with a group picker.
3. Pick the group. Tap **Start**. The bot replies:
   > ✅ Connected this chat to project *Demo Project* (`demo`).
4. Mention the bot in the group: `@your_bot the export button hangs on iOS` → bot replies with `FB-XXXXXX` and the row appears in the dashboard.

### 7e. Add a second project

Repeat step 3 with `--slug app2 --name "Another Project"`, then in the dashboard for `app2` click **Generate Telegram invite** and add the bot to a *different* group. Mentions in that group land in `app2`. Mentions in the demo group still land in `demo`. Same bot, both groups, isolated projects.

## 8. Reset

```bash
docker compose down            # stop containers
docker compose down -v         # also drop the postgres volume (full reset)
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `503 bot ingestion disabled` | `FEEDBOT_BOT_TOKEN` is empty in `.env`. |
| Bot replies "this chat isn't connected" | You haven't run the deep-link onboarding for that group. |
| Bot doesn't see group messages | Privacy mode is on. Talk to BotFather → `/setprivacy` → Disable, then remove and re-add the bot to the group. |
| `claude mcp list` doesn't show feedbot | Run with `--scope user` if you want it across projects, or `--scope project` to pin it to a `.mcp.json` here. |
| Dashboard "Open Telegram" button missing | `FEEDBOT_TELEGRAM_BOT_USERNAME` is empty. |
| API rejects `fbk_live_…` keys | Argon2 verification is exact. Re-issue from the dashboard if unsure. |
