# feedbot-bot

Messaging adapters that ingest into Feedbot.

## Telegram

```bash
export TELEGRAM_BOT_TOKEN=...
export FEEDBOT_API_URL=https://feedbot.io
export FEEDBOT_API_KEY=fbk_live_...
python -m feedbot_bot.telegram_bot
```

The bot creates a feedback row whenever:

- It is mentioned (`@yourbot ...`).
- A user replies to one of the bot's messages.

Use `/status` in the group to see the latest 10 new items.

## WhatsApp

Coming in M2 — a Baileys-based sidecar (Node.js) that you run alongside this package.
