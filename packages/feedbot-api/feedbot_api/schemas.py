from datetime import datetime

from feedbot_core.models import FeedbackStatus, FeedbackType, Severity
from pydantic import BaseModel, Field


class FeedbackIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    type: FeedbackType = FeedbackType.OTHER
    severity: Severity = Severity.MEDIUM
    author_platform: str = "web"
    author_id: str = ""
    author_name: str | None = None


class FeedbackOut(BaseModel):
    id: str
    project_slug: str
    type: FeedbackType
    severity: Severity
    status: FeedbackStatus
    title: str
    body: str
    summary: str | None
    tags: str | None
    author_platform: str
    author_name: str | None
    note: str | None
    reply_to_user: str | None
    user_reply: str | None
    created_at: datetime
    updated_at: datetime


class FeedbackPatch(BaseModel):
    status: FeedbackStatus | None = None
    note: str | None = None
    reply_to_user: str | None = None


class StatsOut(BaseModel):
    by_status: dict[str, int]
    total: int
