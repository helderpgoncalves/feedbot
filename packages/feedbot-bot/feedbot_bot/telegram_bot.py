"""Global Telegram adapter — one bot, N projects.

Project routing is server-side: every ingest call carries `chat_id`, the API
looks it up in `chat_links`, and either ingests against that project or rejects
the message because the chat is not yet onboarded.

Onboarding flow:
1. User clicks "Generate Telegram invite" in the dashboard for project X.
2. Browser opens `https://t.me/<bot>?startgroup=link_<token>`.
3. User picks a group and taps "Start". Telegram sends `/start link_<token>`
   to the bot **inside that group**.
4. Bot calls /v1/internal/redeem-link → server records (chat_id → project X)
   and the bot confirms in the chat.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from feedbot_bot.api_client import FeedbotClient
from feedbot_bot.settings import BotSettings

log = logging.getLogger("feedbot.telegram")


def _ingest_payload(update: Update) -> dict | None:
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return None
    text = msg.text or msg.caption
    if not text:
        return None
    user = update.effective_user
    return {
        "platform": "telegram",
        "chat_id": str(chat.id),
        "title": text[:120],
        "body": text,
        "type": "other",
        "severity": "medium",
        "author_id": str(user.id) if user else "",
        "author_name": (user.full_name if user else None),
    }


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle `/start` — in particular `/start link_<token>` from the deep-link onboarding."""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    args = ctx.args or []
    if not args or not args[0].startswith("link_"):
        if chat.type == ChatType.PRIVATE:
            await msg.reply_text(
                "Hi 👋 I'm Feedbot. Add me to a group and connect it to a project from the dashboard."
            )
        return

    token = args[0][len("link_") :]
    client: FeedbotClient = ctx.application.bot_data["client"]
    result = await client.redeem_link(
        {
            "platform": "telegram",
            "chat_id": str(chat.id),
            "chat_title": chat.title or chat.full_name or None,
            "token": token,
        }
    )
    if not result:
        await msg.reply_text(
            "❌ Couldn't link this chat. The invite may be expired, already used, or the chat is connected to another project."
        )
        return
    await msg.reply_text(
        f"✅ Connected this chat to project *{result['project_name']}* (`{result['project_slug']}`).\n"
        "Mention me with bug reports, feature ideas, or anything you want logged.",
        parse_mode="Markdown",
    )


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Mention or reply-to-bot in a group → create feedback for whatever project owns this chat."""
    client: FeedbotClient = ctx.application.bot_data["client"]
    payload = _ingest_payload(update)
    if not payload:
        return
    try:
        fb = await client.ingest(payload)
    except Exception as exc:
        log.exception("ingest failed: %s", exc)
        await update.effective_message.reply_text("Sorry — couldn't file that feedback right now.")
        return
    if fb is None:
        await update.effective_message.reply_text(
            "This chat isn't connected to any Feedbot project yet. Ask an admin to generate an invite from the dashboard."
        )
        return
    await update.effective_message.reply_text(
        f"Got it — `{fb['id']}` · {fb['type']} · {fb['severity']} severity.",
        parse_mode="Markdown",
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = BotSettings()
    if not settings.telegram_token or not settings.bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN and FEEDBOT_BOT_TOKEN must be set")

    client = FeedbotClient(settings.api_url, settings.bot_token)
    app = Application.builder().token(settings.telegram_token).build()
    app.bot_data["client"] = client

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Entity("mention"), on_message))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, on_message))

    async def on_shutdown(_):
        await client.aclose()

    app.post_shutdown = on_shutdown
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
