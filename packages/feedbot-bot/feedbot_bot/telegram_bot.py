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

Conversation loop (M4):
    - When a user *replies in chat* to a Feedbot message that included an FB-XXXXXX
      id, we treat that as a follow-up on that feedback (`record_user_reply` →
      `user_reply` + status flips to 'triaged').
    - Periodically (every 5s) the bot asks the API for outbound messages
      (`/v1/internal/outbound-pending`) — replies the team queued in
      `reply_to_user` and 'done' notifications. Delivered messages are
      ack'd back so the API marks them as sent.
"""

from __future__ import annotations

import asyncio
import logging
import re

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from feedbot_bot.api_client import FeedbotClient
from feedbot_bot.settings import BotSettings

log = logging.getLogger("feedbot.telegram")

OUTBOUND_POLL_SECONDS = 5
_FB_ID_RE = re.compile(r"\bFB-[A-Z0-9]{4,8}\b")


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
    """Handle `/start` — in particular `/start link_<token>` from deep-link onboarding."""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    args = ctx.args or []
    if not args or not args[0].startswith("link_"):
        if chat.type == ChatType.PRIVATE:
            await msg.reply_text("Hi 👋 I'm Feedbot. Add me to a group and connect it to a project from the dashboard.")
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
            "❌ Couldn't link this chat. The invite may be expired, already used, "
            "or the chat is connected to another project."
        )
        return
    await msg.reply_text(
        f"✅ Connected this chat to project *{result['project_name']}* (`{result['project_slug']}`).\n"
        "Mention me with bug reports, feature ideas, or anything you want logged.",
        parse_mode="Markdown",
    )


async def on_user_reply_to_bot(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """The user replied (Telegram-reply) to a message we sent.

    If our original message contained an FB-XXXXXX id, this is treated as a
    follow-up on that feedback rather than a brand-new ingest. We hand it to
    `/v1/internal/ingest-reply` which matches it against the outbound message
    we recorded.
    """
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not msg.reply_to_message:
        return False
    if not msg.reply_to_message.from_user or not msg.reply_to_message.from_user.is_bot:
        return False  # not a reply to us
    text = msg.text or msg.caption
    if not text:
        return False

    client: FeedbotClient = ctx.application.bot_data["client"]
    payload = {
        "platform": "telegram",
        "chat_id": str(chat.id),
        "replied_to_message_id": str(msg.reply_to_message.message_id),
        "body": text,
        "author_id": str(user.id) if user else "",
        "author_name": user.full_name if user else None,
    }
    try:
        result = await client.ingest_reply(payload)
    except Exception as exc:
        log.exception("ingest_reply failed: %s", exc)
        return False
    if result is None:
        return False  # original message wasn't a feedbot outbound — fall through to ingest
    log.info("user_reply_routed feedback=%s", result.get("id"))
    await msg.set_reaction("👀")  # subtle ack
    return True


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Mentions and replies-to-bot in connected chats become feedback rows.

    A user replying to one of our previous messages is first checked against
    the conversation loop — if it matches a known outbound message it's
    treated as a follow-up on that feedback. Otherwise it falls through to a
    fresh ingest (the original behaviour).
    """
    if await on_user_reply_to_bot(update, ctx):
        return

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
            "This chat isn't connected to any Feedbot project yet. "
            "Ask an admin to generate an invite from the dashboard."
        )
        return
    await update.effective_message.reply_text(
        f"Got it — `{fb['id']}` · {fb['type']} · {fb['severity']} severity.",
        parse_mode="Markdown",
    )


# ─── Outbound delivery loop ─────────────────────────────────────────────────


async def _deliver_one(app: Application, item: dict) -> None:
    """Deliver one queued outbound message and ack the API."""
    client: FeedbotClient = app.bot_data["client"]
    chat_id_raw = item.get("chat_id") or ""
    try:
        chat_id_int = int(chat_id_raw)
    except ValueError:
        log.warning("outbound: skipping non-numeric chat_id=%s", chat_id_raw)
        return

    reply_to = item.get("reply_to_message_id")
    reply_to_int = None
    if reply_to:
        try:
            reply_to_int = int(reply_to)
        except ValueError:
            reply_to_int = None

    body = item["body"]
    sent_id: str | None = None
    ok = False
    err: str | None = None
    try:
        sent = await app.bot.send_message(
            chat_id=chat_id_int,
            text=body,
            reply_to_message_id=reply_to_int,
            parse_mode="Markdown",
        )
        sent_id = str(sent.message_id)
        ok = True
    except Exception as exc:
        err = str(exc)
        log.warning("outbound send failed feedback=%s err=%s", item.get("feedback_public_id"), err)

    try:
        await client.outbound_ack(
            {
                "feedback_public_id": item["feedback_public_id"],
                "kind": item["kind"],
                "body": body,
                "sent_message_id": sent_id,
                "ok": ok,
                "error": err,
            }
        )
    except Exception as exc:
        log.exception("outbound_ack failed: %s", exc)


async def outbound_loop(app: Application) -> None:
    client: FeedbotClient = app.bot_data["client"]
    log.info("outbound_loop started (every %ds)", OUTBOUND_POLL_SECONDS)
    while True:
        try:
            items = await client.outbound_pending(limit=20)
        except Exception as exc:
            log.warning("outbound poll failed: %s", exc)
            items = []
        for item in items:
            await _deliver_one(app, item)
        await asyncio.sleep(OUTBOUND_POLL_SECONDS)


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

    async def post_init(application: Application) -> None:
        application.create_task(outbound_loop(application))

    async def on_shutdown(_):
        await client.aclose()

    app.post_init = post_init
    app.post_shutdown = on_shutdown
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
