# End-to-end test (Docker)

Walks the whole loop locally — without needing SMTP, Telegram, or Claude Code — and then layers each on top once the basics work.

## 0. Prereqs
- Docker Desktop running
- Free port `8000` (API) and `5432` (Postgres)
- (Optional) `jq` for prettier curl output: `brew install jq`

## 1. Set up `.env`

```bash
git clone https://github.com/helderpgoncalves/feedbot.git
cd feedbot
cp .env.example .env

# Generate strong dev secrets — paste each line into .env
python -c "import secrets; print('FEEDBOT_SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('FEEDBOT_BOT_TOKEN='  + secrets.token_urlsafe(32))"
```

Leave `TELEGRAM_BOT_TOKEN` and `FEEDBOT_TELEGRAM_BOT_USERNAME` empty for now. `EMAIL_BACKEND=console` is fine for local dev — magic links print to the API logs.

## 2. Build + start db + api

```bash
docker compose up --build -d db api
docker compose logs -f api
```

Wait for `Uvicorn running on http://0.0.0.0:8000`. Migrations run automatically on startup. Ctrl+C to leave the log tail.

## 3. First-run setup (`/setup`)

Visit <http://localhost:8000>. Because the database is empty, the app redirects you to `/setup`.

1. Enter **your email** + **workspace name** → submit.
2. The magic link prints to the API logs:
   ```bash
   docker compose logs api | grep "magic link"
   # or grep the email backend output:
   docker compose logs api | grep "email/console"
   ```
3. Open the URL in your browser → you land in `/app` as the **owner**.

> The `/setup` route only works while the `users` table is empty. Once the owner is created it returns `410 Gone`. From here on, the only way new users get in is via an invite.

## 4. Create a project + issue an API key

In `/app`:

1. **New project** form → slug `demo`, name "Demo Project" → Create.
2. Click into the project → **Issue key** with label *"Claude Code on laptop"* → copy the `fbk_live_...` it shows you. (You won't see it again.)

Or, scripted, without clicking:

```bash
docker compose exec api python scripts/seed.py \
  --email someone-else@example.com --slug demo --name "Demo Project"
```

> The `seed.py` script is mostly for fresh installs. After bootstrap, the dashboard is the canonical path.

## 5. Smoke-test the API with curl

```bash
KEY="fbk_live_..."   # paste from step 4

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

## 6. Invite a teammate

In `/app/team`:

1. **Invite a teammate** form → email + role (`admin` or `member`) → Send invite.
2. The invite link prints to the API logs (`grep "email/console"`). Copy it and open in an incognito window.
3. Tap **Accept invite and sign in** → the teammate lands in `/app`.
4. As an admin, go back to your owner session → project page → **Members** → add the new user.
5. Confirm the new user (in the incognito window) only sees projects they were added to.

## 7. Hook up Claude Code via MCP (HTTP, recommended)

The Feedbot API exposes the MCP protocol natively at `/mcp` over Streamable HTTP. **No extra process to run** — the same `fbk_*` key authenticates JSON-RPC calls.

```bash
claude mcp add feedbot \
  --transport http \
  --header "Authorization: Bearer $KEY" \
  http://localhost:8000/mcp/

claude mcp list   # should show feedbot (http)
```

Or commit a project-scoped `.mcp.json`:

```json
{
  "mcpServers": {
    "feedbot": {
      "type": "http",
      "url": "http://localhost:8000/mcp/",
      "headers": {
        "Authorization": "Bearer fbk_live_..."
      }
    }
  }
}
```

Inside Claude Code: *"What feedback is open in the demo project?"* — Claude calls `list_feedbacks` and prints the row from step 5.

> Reference: <https://code.claude.com/docs/en/mcp>. The stdio package (`feedbot-mcp`) is deprecated; use HTTP for new setups.

### Quick curl smoke test

```bash
# initialize
curl -s -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'

# list tools
curl -s -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}'
```

## 8. Telegram (one bot, N projects)

The bot is **global** — the same bot process serves every project; routing is server-side via `chat_id → project_members` links.

### 8a. Create the bot
1. DM [@BotFather](https://t.me/BotFather) → `/newbot` → save the token.
2. `/setprivacy` → **Disable** (so the bot can read group messages).
3. `/setcommands` → paste:
   ```
   start - Onboard or show help
   ```

### 8b. Configure `.env`

```env
TELEGRAM_BOT_TOKEN=123456:AA-Your-Real-Token
FEEDBOT_TELEGRAM_BOT_USERNAME=your_bot_user_without_at
```

(`FEEDBOT_BOT_TOKEN` was already set in step 1.)

### 8c. Start the bot service

```bash
docker compose --profile bot up -d --build bot
docker compose logs -f bot
```

### 8d. Connect a Telegram group to a project

1. Dashboard → project page → **Generate Telegram invite**.
2. Click **Open Telegram → Add to group**. Telegram opens with a group picker.
3. Pick the group. Tap **Start**. The bot replies:
   > ✅ Connected this chat to project *Demo Project* (`demo`).
4. Mention the bot: `@your_bot the export button hangs on iOS` → bot replies with `FB-XXXXXX` and the row appears in the dashboard.

### 8e. Add a second project

Create another project (slug `app2`), generate an invite for it, and add the bot to a **different** group. Mentions in `app2`'s group land in `app2`'s inbox; the demo group keeps landing in `demo`. **Same bot, both groups, isolated projects.**

## 9. Reset

```bash
docker compose down            # stop containers
docker compose down -v         # also drop the postgres volume (full reset)
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Browser stays at `/setup` after login | Cookies blocked, or your hostname differs from `FEEDBOT_BASE_URL`. |
| `/login` returns `503 Email delivery not configured` | Production fail-safe: you're serving HTTPS but `EMAIL_BACKEND=console`. Set `EMAIL_BACKEND=smtp` + the `SMTP_*` vars. |
| `503 bot ingestion disabled` on bot startup | `FEEDBOT_BOT_TOKEN` is empty in `.env`. |
| Bot replies *"this chat isn't connected"* | You haven't run the deep-link onboarding for that group. |
| Bot doesn't see group messages | Privacy mode is on. BotFather → `/setprivacy` → Disable, then remove + re-add the bot to the group. |
| Member sees no projects | They haven't been added. As admin → project page → **Members** → add them. |
| `claude mcp list` doesn't show feedbot | Use `--scope user` for cross-project, or `--scope project` for a committed `.mcp.json`. |
| Dashboard "Open Telegram" button missing | `FEEDBOT_TELEGRAM_BOT_USERNAME` is empty in `.env`. |
| API rejects `fbk_live_…` keys | Re-issue from the dashboard. The Argon2 hash is exact; never type or transcribe keys. |
