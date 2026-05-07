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


# ─── Auth & identity (consumed by the SPA in apps/web) ─────────────────────


class LoginIn(BaseModel):
    """JSON body for ``POST /v1/auth/login``.

    The SPA POSTs to this with the user's email. Same enumeration-resistant
    behaviour as the legacy form endpoint: response is identical whether the
    email exists or not.
    """

    email: str = Field(min_length=3, max_length=255)


class LoginOut(BaseModel):
    """Response from ``POST /v1/auth/login``.

    The PKCE nonce ships back in the ``mlnonce`` cookie (httpOnly), not in
    this body — the SPA never sees it directly.
    """

    sent: bool = Field(description="Always true; whether the email exists is intentionally hidden.")


class SessionOut(BaseModel):
    """One row from ``GET /v1/auth/sessions``.

    ``id`` is the full session token; sensitive — only the owner sees their
    own sessions, and the field is shown so the user can revoke a specific
    one from the future Security page.
    """

    id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip: str | None
    is_current: bool = Field(description="True for the session that authenticated this request.")


class ProjectSummary(BaseModel):
    """Compact view of a project — used in ``/v1/me`` and listings."""

    slug: str
    name: str
    created_at: datetime


class MeOut(BaseModel):
    """Response from ``GET /v1/me`` — everything the SPA needs at boot."""

    user: dict[str, object] = Field(
        description="Identity + role. Keys: id, email, role, tenant_id."
    )
    tenant: dict[str, object] = Field(
        description="Workspace-level info. Keys: id, name."
    )
    projects: list[ProjectSummary] = Field(
        description="Projects this user can see (admins/owners: all; members: their assignments)."
    )
    is_setup_complete: bool = Field(
        description="False only when the database is empty (i.e. /setup is still active)."
    )


# ─── Projects, API keys, chat links ─────────────────────────────────────────


class ProjectIn(BaseModel):
    """Body for ``POST /v1/projects``."""

    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=120)


class ProjectOut(BaseModel):
    """Detailed project view — superset of ``ProjectSummary``."""

    slug: str
    name: str
    created_at: datetime
    feedback_count_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Counts grouped by status for the badge in the UI.",
    )


class ApiKeyOut(BaseModel):
    """List/get view of an API key. The secret is never re-rendered."""

    id: int
    label: str
    prefix: str = Field(description="First 12 chars of the key, e.g. 'fbk_live_AbCdEf12'.")
    scope: str = Field(description="read | write | admin")
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    """Response from ``POST /v1/projects/{slug}/api-keys``.

    ``key`` is the **only** time the secret is exposed. Store it now or rotate.
    """

    key: str = Field(description="Full secret (fbk_*); shown once, never re-rendered.")


class ApiKeyIn(BaseModel):
    """Body for ``POST /v1/projects/{slug}/api-keys``."""

    label: str = Field(min_length=1, max_length=120)
    scope: str = Field(default="write", pattern=r"^(read|write|admin)$")


class ChatLinkOut(BaseModel):
    id: int
    platform: str
    chat_id: str
    title: str | None
    created_at: datetime


class ChatLinkTokenOut(BaseModel):
    """Response from ``POST /v1/projects/{slug}/chat-link-tokens``.

    ``deep_link`` is empty when ``FEEDBOT_TELEGRAM_BOT_USERNAME`` is unset on
    the deployment; the SPA hides the "Open Telegram" button in that case.
    """

    token: str
    deep_link: str
    expires_at: datetime
