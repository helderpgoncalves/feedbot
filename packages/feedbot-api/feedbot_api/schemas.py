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


class SetupStatusOut(BaseModel):
    """Response from ``GET /v1/setup-status``.

    The SPA polls this once at boot and routes to ``/setup`` when ``required``
    is true. After bootstrap the endpoint reports ``required=False`` forever
    (until the deployment is wiped), so the SPA caches it conservatively.
    """

    required: bool = Field(
        description="True only while the users table is empty. Once an owner exists, the endpoint flips to false permanently for this DB."
    )


class SetupIn(BaseModel):
    """Body for ``POST /v1/setup`` — first-run owner bootstrap.

    Only accepted while the users table is empty; once an owner exists this
    endpoint returns 410 Gone. The owner gets a magic-link emailed (or, on
    deployments without SMTP, surfaced in the response) so they can sign in
    immediately.
    """

    email: str = Field(min_length=3, max_length=255)
    tenant_name: str = Field(default="", max_length=120)


class SetupOut(BaseModel):
    """Response from ``POST /v1/setup``.

    ``fallback_link`` is only populated when SMTP isn't configured (e.g.
    ``EMAIL_BACKEND=console`` in production) so the owner isn't locked out
    of their own instance. It's a single-use link with a 15-minute TTL; the
    SPA renders it as a "click here to sign in" button.
    """

    email: str
    delivered: bool = Field(
        description="True when the magic-link email was handed off to the configured backend without raising."
    )
    fallback_link: str | None = Field(
        default=None,
        description="When SMTP isn't configured, the magic link is returned here so the bootstrapping admin can copy it.",
    )


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


# ─── LLM settings & audit (sensitive — see docstrings) ─────────────────────


class LLMSettingsOut(BaseModel):
    """View of project LLM settings.

    The encrypted API key is **never** included in this response. Whether one
    is configured is exposed only as the boolean ``has_api_key``. The provider
    error from the last test call (``last_test_error``) is truncated to 240
    characters to limit accidental key leakage if the provider echoed it back.
    """

    provider: str
    model: str | None
    enabled: bool
    monthly_budget_usd: float | None
    has_api_key: bool = Field(description="True when an encrypted key is stored.")
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_error: str | None = Field(
        description="Truncated provider error from the last /llm-test call."
    )
    month_to_date_usd: float = Field(description="Sum of usd_cost for this calendar month.")


class LLMSettingsIn(BaseModel):
    """Body for ``PUT /v1/projects/{slug}/llm-settings``.

    Partial-update semantics:
      * Omit ``api_key`` to keep the existing encrypted key untouched.
      * Send a non-empty ``api_key`` string to set / rotate it.
      * Send an empty string to **clear** the key (must also set
        ``enabled=false`` since classification cannot run without one).
    The strict pattern is enforced server-side.
    """

    provider: str = Field(min_length=1, max_length=32, pattern=r"^(none|[a-z][a-z0-9_-]*)$")
    model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, description="Plaintext key; encrypted server-side.")
    enabled: bool = False
    monthly_budget_usd: float | None = Field(default=None, ge=0)


class LLMTestOut(BaseModel):
    """Response from ``POST /v1/projects/{slug}/llm-test``."""

    ok: bool
    status: str = Field(description="ok | refused | error | over_budget | disabled")
    provider: str | None
    model: str | None
    latency_ms: int
    usd_cost: float
    error_text: str | None = Field(description="Truncated to 240 chars; never echoes back the key.")


class LLMCallOut(BaseModel):
    """One row from ``GET /v1/projects/{slug}/llm-calls``. Used for the audit table."""

    id: int
    provider: str
    model: str
    purpose: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    usd_cost: float
    latency_ms: int
    status: str
    error_text: str | None
    created_at: datetime


class ProvidersOut(BaseModel):
    """Response from ``GET /v1/llm/providers`` — populated dynamically from the
    feedbot_core.llm registry. The SPA uses this to render the provider/model
    dropdowns without hardcoding any names client-side."""

    providers: dict[str, dict[str, object]] = Field(
        description="Keyed by provider name; each entry has default_model + available_models."
    )


# ─── Invites ───────────────────────────────────────────────────────────────


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: str = Field(default="member", pattern=r"^(admin|member)$")
    project_slug: str | None = Field(default=None, max_length=64)


class InviteOut(BaseModel):
    id: int
    email: str
    role: str
    project_slug: str | None
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    invited_by_email: str | None


class InvitePreviewOut(BaseModel):
    """Response from ``GET /v1/invites/preview?token=...`` — no auth required.

    Designed so the SPA's "Accept invite" page can show context (workspace name,
    email, role) before the user clicks "Accept". Returns 404 for any invalid
    state; never reveals whether the email exists in another tenant.
    """

    email: str
    role: str
    tenant_name: str
    project_name: str | None
    expires_at: datetime


class InviteAcceptIn(BaseModel):
    token: str = Field(min_length=8, max_length=128)


# ─── Members & team ────────────────────────────────────────────────────────


class TenantUserOut(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime


class ProjectMemberAddIn(BaseModel):
    user_id: int


class TenantUserPatchIn(BaseModel):
    """Body for ``PATCH /v1/tenant/users/{id}``. Only ``role`` is mutable."""

    role: str = Field(pattern=r"^(admin|member)$")
