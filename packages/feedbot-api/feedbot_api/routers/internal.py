"""Internal endpoints used by the bot service.

Authenticated with FEEDBOT_BOT_TOKEN (shared secret, server-side only) — never an
end-user API key. The bot resolves project from chat_id; if the chat is not
linked to any project, ingestion is rejected (the chat must be onboarded first
via /v1/internal/redeem-link, triggered by /start link_<token> in Telegram).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session, require_bot_token
from feedbot_api.schemas import FeedbackOut
from feedbot_api.routers.v1 import _to_out
from feedbot_core.models import FeedbackType, Project, Severity
from feedbot_core.repos import (
    create_feedback,
    project_for_chat,
    redeem_chat_link_token,
)

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
    )
    return _to_out(fb, project)


@router.post("/redeem-link", response_model=RedeemOut)
async def redeem_link(body: RedeemIn, session: AsyncSession = Depends(get_session)):
    link = await redeem_chat_link_token(
        session, body.token, body.platform, body.chat_id, body.chat_title
    )
    if not link:
        raise HTTPException(400, "invalid, expired, used, or chat already linked")
    project = await session.get(Project, link.project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return RedeemOut(project_slug=project.slug, project_name=project.name)
