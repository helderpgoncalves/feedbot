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
        description=(
            "True only while the users table is empty. Once an owner exists "
            "the endpoint flips to false permanently for this DB."
        )
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
        description=(
            "When SMTP isn't configured, the magic link is returned here "
            "so the bootstrapping admin can copy it."
        ),
    )


class SignupIn(BaseModel):
    """Body for ``POST /v1/signup`` — multi-tenant cloud self-serve.

    Distinct from ``SetupIn`` (single-tenant first-run bootstrap). Both
    accept ``tenant_name`` optionally; ``signup`` falls back to the email's
    local-part when omitted, ``setup`` falls back the same way.
    """

    email: str = Field(min_length=3, max_length=255)
    tenant_name: str = Field(default="", max_length=120)


class SignupOut(BaseModel):
    """Response from ``POST /v1/signup``.

    Mirrors ``LoginOut.sent`` deliberately — the SPA shows the same
    "check your email" success card after either flow, and the response
    is identical whether the email is new, already registered, or
    rejected by rate limiting. Hides whether an email is registered to
    prevent enumeration.
    """

    sent: bool = Field(
        description="Always true on success; whether the email was new is intentionally hidden."
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


# ─── Admin / orchestrator (self-host only) ─────────────────────────────────


class EmailConfigOut(BaseModel):
    """Current SMTP config for the dashboard's Settings → Email section.

    The encrypted password is **never** returned. ``has_password`` exposes
    only whether one is stored. ``configured`` is true when the orchestrator
    has enough to actually send mail (host + port + sender at minimum).
    """

    host: str | None
    port: int | None
    user: str | None
    sender: str | None
    has_password: bool = Field(description="True when an encrypted password is stored.")
    configured: bool = Field(
        description="True when the API would route magic links through SMTP."
    )


class EmailConfigIn(BaseModel):
    """Body for ``POST /v1/admin/email/config``.

    ``password`` is **tri-state** (mirrors the LLM-key pattern):

      * ``None``       — keep the stored password untouched.
      * ``""``         — clear it (fall back to no-auth SMTP / console).
      * non-empty str  — set / rotate it.

    The other fields are plain replace semantics: send the value you want
    to persist (or empty string to clear).
    """

    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = Field(default=None, max_length=255)
    password: str | None = Field(
        default=None,
        description="Plaintext; encrypted server-side. Tri-state: None=keep, ''=clear, str=set.",
    )
    sender: str | None = Field(default=None, max_length=255)


class EmailTestIn(BaseModel):
    """Body for ``POST /v1/admin/email/test``."""

    to: str = Field(
        min_length=3,
        max_length=255,
        description="Recipient address for the test send. Usually the owner's email.",
    )


class EmailTestOut(BaseModel):
    """Outcome of ``POST /v1/admin/email/test``.

    Always returns 200 with a structured outcome — even when SMTP rejects
    the request, so the UI can render the raw provider response. The error
    string is truncated to 240 chars to limit accidental credential leakage
    if the SMTP server echoes part of the username.
    """

    ok: bool
    error: str | None = Field(
        default=None,
        description="Truncated SMTP / connection error if ``ok`` is false.",
    )


class BotProfileOut(BaseModel):
    """Subset of Telegram's ``getMe`` payload safe to expose to the SPA.

    The bot ``id`` is the public numeric identifier (it shows up in
    every ``t.me/<username>`` link); ``username`` and ``first_name``
    are likewise public. We deliberately don't expose anything the
    bot's owner could rotate as a security measure (e.g. the secret
    chat-link path) — Telegram has no such field on ``getMe`` today
    but the allow-list keeps us safe if it changes.
    """

    id: int
    username: str | None
    first_name: str | None
    can_join_groups: bool | None = None
    can_read_all_group_messages: bool | None = None


class BotConfigOut(BaseModel):
    """Current Telegram bot config for Settings → Telegram bot.

    The encrypted token is **never** returned. ``has_token`` exposes
    only whether one is stored. ``configured`` is true when both
    token and username are present (the username powers the
    ``t.me/<username>?startgroup=…`` deep link the SPA shows).
    """

    username: str | None
    has_token: bool
    configured: bool


class BotConfigIn(BaseModel):
    """Body for ``POST /v1/admin/bot/config``.

    ``token`` follows the same tri-state pattern as the SMTP
    password — ``None`` keeps, ``""`` clears, any other string
    rotates / sets. The username is plain replace semantics; the
    leading ``@`` is stripped server-side for forgiveness.
    """

    token: str | None = Field(
        default=None,
        description="Plaintext Telegram bot token; encrypted server-side.",
    )
    username: str | None = Field(default=None, max_length=64)


class BotTestIn(BaseModel):
    """Body for ``POST /v1/admin/bot/test``.

    The optional ``token`` lets the operator validate a fresh token
    *before* saving — common pattern when a user pastes from
    BotFather. When omitted the test runs against the currently
    stored token.
    """

    token: str | None = Field(
        default=None,
        description="Optional override; tested as-is without persistence.",
    )


class BotTestOut(BaseModel):
    """Outcome of ``POST /v1/admin/bot/test``.

    ``ok=True`` carries the bot profile straight back so the UI can
    show "Connected as @feedbot_acme_bot" without a second round
    trip. ``ok=False`` carries a truncated error.
    """

    ok: bool
    profile: BotProfileOut | None = None
    error: str | None = Field(
        default=None,
        description="Truncated Telegram error / network failure if ok=False.",
    )


class BotChatOut(BaseModel):
    """One row of the tenant-wide chat-links list.

    Mirrors ``ChatLinkOut`` but adds ``project_slug`` / ``project_name``
    so the Settings page can show "@my-bot is linked in 4 projects"
    without per-row joins from the SPA.
    """

    id: int
    platform: str
    chat_id: str
    title: str | None
    project_slug: str
    project_name: str
    created_at: datetime


class ProxyConfigOut(BaseModel):
    """Current Caddy / domain config for Settings → Domain & HTTPS.

    ``configured`` is true when both a domain and a Let's Encrypt
    contact email are stored — that's the minimum the orchestrator
    needs to push a TLS-enabled config. ``https_enabled`` reflects
    the persisted toggle; the live cert provisioning state is
    surfaced separately via ``ProxyStatusOut``.
    """

    domain: str | None
    letsencrypt_email: str | None
    https_enabled: bool
    configured: bool


class ProxyConfigIn(BaseModel):
    """Body for ``POST /v1/admin/proxy/config``.

    Both fields are validated server-side before any orchestrator
    work happens — a bad domain or empty email returns 422 *before*
    we touch the Caddy admin API, so the SPA's pre-flight has a
    clear contract.
    """

    domain: str = Field(
        min_length=3,
        max_length=253,
        # Hostname-only: no scheme, no path, no port. Caddy parses
        # the cleaned hostname; the SPA sends the user-typed value
        # but trims whitespace before submit.
        pattern=r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$",
    )
    letsencrypt_email: str = Field(
        min_length=3,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )


class ProxyStatusOut(BaseModel):
    """Polled view of the current Caddy provisioning state.

    The SPA hits this every ~3s while the chip shows "applying".
    ``configured`` is the orchestrator's read on whether Caddy has
    a TLS automation policy registered for ``domain``; ``error``
    is set on the unhappy path so the UI can surface the raw
    Caddy admin API response.
    """

    domain: str | None
    configured: bool
    https_enabled: bool
    policy_count: int | None = None
    error: str | None = None


class ProxyDnsCheckIn(BaseModel):
    """Body for ``POST /v1/admin/proxy/dns-check``."""

    domain: str = Field(
        min_length=3,
        max_length=253,
        pattern=r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$",
    )


class ProxyDnsCheckOut(BaseModel):
    """Pre-flight DNS resolution result.

    ``resolved_ips`` is the A/AAAA record set the resolver returned
    for ``domain``. ``server_ip`` is best-effort: the API container
    sees its outbound NAT IP, not necessarily the public IP the
    user pointed DNS at — so we surface ``matches`` only as a
    soft hint, never as a hard block.
    """

    domain: str
    resolved_ips: list[str]
    server_ip: str | None
    matches: bool
    error: str | None = None


class SystemServiceOut(BaseModel):
    """One service row from ``GET /v1/admin/system/status``.

    State strings come straight from ``docker compose ps`` (running,
    exited, restarting, paused, etc.); we don't normalise so
    operators see the same vocabulary they get from the CLI.
    """

    name: str
    state: str
    image: str | None = None
    status: str | None = None


class SystemStatusOut(BaseModel):
    """High-level health snapshot.

    ``ok=True`` when every known service is in ``running`` state.
    The ``error`` field carries the raw compose error if the ``ps``
    invocation fails — UI surfaces it so the operator can debug.
    """

    ok: bool
    version: str
    services: list[SystemServiceOut]
    error: str | None = None


class SystemRestartIn(BaseModel):
    """Body for ``POST /v1/admin/system/restart``.

    ``service`` is one of the known compose services (or ``None``
    to restart everything). The orchestrator validates against
    ``compose.KNOWN_SERVICES`` before shelling out.
    """

    service: str | None = Field(default=None, max_length=32)


class AutostartStatusOut(BaseModel):
    """Result of ``GET /v1/admin/system/autostart``.

    ``platform`` is the orchestrator's enum value
    (linux-systemd, linux-other, macos-launchd, unknown).
    ``unit_path`` is the systemd unit / launchd plist path or
    ``None`` on unsupported platforms; ``manual_instructions`` is
    set when the platform doesn't support auto-managed startup so
    the UI can render copy-paste init snippets.
    """

    platform: str
    enabled: bool
    unit_path: str | None
    manual_instructions: str | None = None


class TelemetryConfigOut(BaseModel):
    enabled: bool


class TelemetryConfigIn(BaseModel):
    enabled: bool


class BackupOut(BaseModel):
    """One row of the backups directory listing."""

    filename: str
    size_bytes: int
    created_at: datetime


class UpdatesOut(BaseModel):
    """Result of ``GET /v1/admin/system/updates``.

    ``available`` is a server-side comparison so the SPA never has
    to ship semver logic. ``error`` is set on registry failures —
    the UI surfaces it as a soft warning rather than a hard fail
    so an offline registry doesn't block the rest of the page.
    """

    current: str
    latest: str | None
    available: bool
    error: str | None = None


class UpdateApplyOut(BaseModel):
    """Outcome of ``POST /v1/admin/system/updates/apply``.

    ``ok=True`` means ``compose pull`` and ``compose up -d``
    finished without error; the api container then runs
    ``alembic upgrade head`` on its boot command before serving
    again.
    """

    ok: bool
    message: str | None = None
