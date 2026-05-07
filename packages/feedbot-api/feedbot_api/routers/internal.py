"""Internal endpoints used by the bot service.

Authenticated with FEEDBOT_BOT_TOKEN (shared secret, server-side only) — never an
end-user API key. The bot resolves project from chat_id; if the chat is not
linked to any project, ingestion is rejected (the chat must be onboarded first
via /v1/internal/redeem-link, triggered by /start link_<token> in Telegram).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from feedbot_core.llm import classify_feedback
from feedbot_core.models import FeedbackType, Project, Severity
from feedbot_core.repos import (
    create_feedback,
    find_feedbacks_pending_done_notification,
    find_feedbacks_with_pending_reply,
    get_feedback_by_outbound_message,
    mark_done_notified,
    mark_reply_delivered,
    project_for_chat,
    record_user_reply,
    redeem_chat_link_token,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session, require_bot_token
from feedbot_api.routers.v1 import _to_out
from feedbot_api.schemas import FeedbackOut

log = logging.getLogger("feedbot.api.ingest")

router = APIRouter(
    prefix="/v1/internal",
    tags=["internal"],
    dependencies=[Depends(require_bot_token)],
)


class IngestIn(BaseModel):
    platform: str = Field(pattern=r"^(telegram|whatsapp)$")
    chat_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    type: FeedbackType = FeedbackType.OTHER
    severity: Severity = Severity.MEDIUM
    author_id: str
    author_name: str | None = None


class IngestReplyIn(BaseModel):
    """Inbound reply from a user — they replied to one of our outbound messages."""

    platform: str = Field(pattern=r"^(telegram|whatsapp)$")
    chat_id: str = Field(min_length=1, max_length=128)
    replied_to_message_id: str = Field(min_length=1, max_length=64)
    body: str = Field(min_length=1)
    author_id: str
    author_name: str | None = None


class OutboundItem(BaseModel):
    feedback_public_id: str
    platform: str
    chat_id: str
    kind: str  # "reply" | "done_notification"
    body: str
    reply_to_message_id: str | None = None


class OutboundAckIn(BaseModel):
    feedback_public_id: str
    kind: str
    body: str
    sent_message_id: str | None = None
    ok: bool
    error: str | None = None


class RedeemIn(BaseModel):
    platform: str = Field(pattern=r"^(telegram|whatsapp)$")
    chat_id: str = Field(min_length=1, max_length=128)
    chat_title: str | None = None
    token: str = Field(min_length=8, max_length=64)


class RedeemOut(BaseModel):
    project_slug: str
    project_name: str


@router.post("/ingest", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def ingest(body: IngestIn, session: AsyncSession = Depends(get_session)):
    project = await project_for_chat(session, body.platform, body.chat_id)
    if not project:
        raise HTTPException(404, "chat is not linked to any project")

    fb = await create_feedback(
        session,
        project_id=project.id,
        title=body.title,
        body=body.body,
        type=body.type,
        severity=body.severity,
        author_platform=body.platform,
        author_id=body.author_id,
        author_name=body.author_name,
        author_chat_id=body.chat_id,
    )

    # Best-effort LLM classification. Errors are audited in llm_calls and never
    # block ingestion. If the project hasn't enabled an LLM, this is a no-op.
    outcome = await classify_feedback(
        session,
        project_id=project.id,
        text=body.body,
        feedback_id=fb.id,
        project_hint=f"{project.name} ({project.slug})",
    )
    if outcome.ok and outcome.classification is not None:
        c = outcome.classification
        fb.type = FeedbackType(c.type)
        fb.severity = Severity(c.severity)
        fb.summary = c.summary
        fb.tags = ",".join(c.tags) if c.tags else None
        # store language as a tag-prefix so the existing tags column carries everything
        # without another migration; downstream UI can split on `lang:`.
        if c.language:
            existing = fb.tags or ""
            fb.tags = (f"lang:{c.language}," + existing).rstrip(",")
        await session.flush()
        log.info(
            "ingest_classified id=%s type=%s severity=%s lang=%s sentiment=%s tags=%s",
            fb.public_id,
            c.type,
            c.severity,
            c.language,
            c.sentiment,
            c.tags,
        )

    return _to_out(fb, project)


@router.post("/redeem-link", response_model=RedeemOut)
async def redeem_link(body: RedeemIn, session: AsyncSession = Depends(get_session)):
    link = await redeem_chat_link_token(session, body.token, body.platform, body.chat_id, body.chat_title)
    if not link:
        raise HTTPException(400, "invalid, expired, used, or chat already linked")
    project = await session.get(Project, link.project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return RedeemOut(project_slug=project.slug, project_name=project.name)


@router.post("/ingest-reply", response_model=FeedbackOut)
async def ingest_reply(body: IngestReplyIn, session: AsyncSession = Depends(get_session)):
    """The user replied (in chat) to one of our outbound messages.

    The bot detects 'this Telegram message is a reply to one we sent' and posts
    here. We resolve which feedback owns that outbound message_id and record
    the body as user_reply, flipping status back to 'triaged' so Claude (or a
    human) sees it on the next read.
    """
    fb = await get_feedback_by_outbound_message(session, body.platform, body.chat_id, body.replied_to_message_id)
    if not fb:
        raise HTTPException(404, "no feedback matched that reply")
    project_id = fb.project_id
    public_id = fb.public_id
    await record_user_reply(session, fb, body.body)
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    log.info(
        "user_reply_received feedback=%s project=%s author_id=%s",
        public_id,
        project.slug,
        body.author_id,
    )
    return _to_out(fb, project)


@router.get("/outbound-pending", response_model=list[OutboundItem])
async def outbound_pending(limit: int = 20, session: AsyncSession = Depends(get_session)) -> list[OutboundItem]:
    """The bot polls this every few seconds and delivers each item to chat.

    Two kinds of outbound messages live in the same queue: queued replies (the
    team or Claude wrote in `reply_to_user`) and done notifications (status
    just flipped to `done`). Both are delivered to the same chat where the
    feedback was first reported, so the conversation stays in one thread.
    """
    items: list[OutboundItem] = []

    for fb in await find_feedbacks_with_pending_reply(session, limit=limit):
        items.append(
            OutboundItem(
                feedback_public_id=fb.public_id,
                platform=fb.author_platform,
                chat_id=fb.author_chat_id or "",
                kind="reply",
                body=f"[{fb.public_id}] {fb.reply_to_user}",
                reply_to_message_id=fb.last_outbound_message_id,
            )
        )
    for fb in await find_feedbacks_pending_done_notification(session, limit=limit):
        items.append(
            OutboundItem(
                feedback_public_id=fb.public_id,
                platform=fb.author_platform,
                chat_id=fb.author_chat_id or "",
                kind="done_notification",
                body=(f"✅ {fb.public_id} resolved.\n" + (fb.note.splitlines()[-1] if fb.note else fb.title)),
                reply_to_message_id=fb.last_outbound_message_id,
            )
        )

    return items[:limit]


@router.post("/outbound-ack")
async def outbound_ack(body: OutboundAckIn, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """The bot confirms it delivered (or failed to deliver) an outbound message."""
    from feedbot_core.models import Feedback
    from sqlalchemy import select as _select

    row = await session.execute(_select(Feedback).where(Feedback.public_id == body.feedback_public_id))
    fb = row.scalar_one_or_none()
    if not fb:
        raise HTTPException(404, "feedback not found")

    if not body.ok:
        log.warning(
            "outbound_failed feedback=%s kind=%s error=%s",
            fb.public_id,
            body.kind,
            body.error,
        )
        return {"status": "noted"}

    if body.kind == "reply":
        await mark_reply_delivered(session, fb, body.body, body.sent_message_id)
    elif body.kind == "done_notification":
        await mark_done_notified(session, fb, body.sent_message_id)
    else:
        raise HTTPException(400, f"unknown kind: {body.kind}")

    log.info(
        "outbound_delivered feedback=%s kind=%s message_id=%s",
        fb.public_id,
        body.kind,
        body.sent_message_id,
    )
    return {"status": "ok"}
