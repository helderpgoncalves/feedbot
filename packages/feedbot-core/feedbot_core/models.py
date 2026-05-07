from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class FeedbackType(StrEnum):
    BUG = "bug"
    FEATURE = "feature"
    QUESTION = "question"
    OTHER = "other"


class FeedbackStatus(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    WONT_FIX = "wont_fix"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Role(StrEnum):
    """Tenant-level role.

    Authorization is intentionally simple:
        owner   — bootstrap user, can do anything; cannot be modified by anyone else.
        admin   — can invite, create/delete projects, manage keys and members.
        member  — sees only projects they are a member of; can triage feedback there.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[Role] = mapped_column(String(16), default=Role.MEMBER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="users")

    @property
    def is_admin(self) -> bool:
        return self.role in (Role.OWNER, Role.ADMIN)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="projects")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    chats: Mapped[list["ChatLink"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    feedbacks: Mapped[list["Feedback"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_project_tenant_slug"),)


class ProjectMember(Base):
    """Joins users to projects. Members (non-admin) can only see projects they're in."""

    __tablename__ = "project_members"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="members")


class Invite(Base):
    """Single-use invitation to join a tenant (optionally pre-attached to a project)."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[Role] = mapped_column(String(16), default=Role.MEMBER)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(32), default="write")  # read | write | admin
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="api_keys")


class ChatLink(Base):
    """Maps a Telegram chat / WhatsApp jid to a project."""

    __tablename__ = "chat_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(16))  # telegram | whatsapp
    chat_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="chats")

    __table_args__ = (UniqueConstraint("platform", "chat_id", name="uq_chat_platform_id"),)


class Feedback(Base):
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # FB-XXXXXX
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)

    type: Mapped[FeedbackType] = mapped_column(String(16), default=FeedbackType.OTHER)
    severity: Mapped[Severity] = mapped_column(String(16), default=Severity.MEDIUM)
    status: Mapped[FeedbackStatus] = mapped_column(String(16), default=FeedbackStatus.NEW)

    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True)  # csv

    author_platform: Mapped[str] = mapped_column(String(16))  # telegram | whatsapp | web
    author_id: Mapped[str] = mapped_column(String(128))
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Where to deliver replies + done notifications. For Telegram this is the
    # numeric chat_id (negative for groups); for whatsapp it's the jid; for
    # web/mcp it's empty (replies are not delivered out-of-band).
    author_chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_to_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Outbound delivery tracking — set when the bot has actually delivered the
    # corresponding outbound message to the chat. Used by the worker to dedupe.
    reply_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_sent_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notified_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last Telegram message_id we sent for this feedback. The bot uses this to
    # match incoming "reply-to" messages back to a specific feedback.
    last_outbound_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="feedbacks")

    __table_args__ = (
        Index("ix_feedbacks_project_status", "project_id", "status"),
        Index("ix_feedbacks_project_created", "project_id", "created_at"),
        Index("ix_feedbacks_outbound_pending", "reply_to_user", "reply_sent_at"),
    )


class MagicLinkToken(Base):
    """Single-use email login token."""

    __tablename__ = "magic_link_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatLinkToken(Base):
    """Single-use token used to bind a chat (Telegram group / WhatsApp jid) to a project.

    Issued from the dashboard, redeemed by the bot when a user starts the bot
    in their group via a deep link (`t.me/<bot>?startgroup=link_<token>`).
    """

    __tablename__ = "chat_link_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_email: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramUpdate(Base):
    """Idempotency record so duplicate Telegram updates never double-write."""

    __tablename__ = "telegram_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectLLMSettings(Base):
    """Per-project LLM configuration for inbound classification.

    The provider name is a free-form string (not an enum) so adding a new
    provider is a one-class change in feedbot_core/llm/providers/. The string
    is resolved against the runtime registry in feedbot_core.llm.base.
    """

    __tablename__ = "project_llm_settings"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="none")
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Fernet-encrypted (urlsafe base64); decrypted at use-time, never logged.
    encrypted_api_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Runaway-cost protection: if set, the classifier stops calling once
    # the running USD total for the calendar month exceeds this value.
    monthly_budget_usd: Mapped[float | None] = mapped_column(nullable=True)

    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMCall(Base):
    """One row per LLM API call. Used for cost tracking, audit, and debugging.

    Never store prompts/responses verbatim — only token counts and metadata.
    Pricing is computed server-side from feedbot_core/llm/pricing.py at insert
    time so historical costs survive provider price changes.
    """

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    feedback_id: Mapped[int | None] = mapped_column(
        ForeignKey("feedbacks.id", ondelete="SET NULL"), nullable=True, index=True
    )

    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(32))  # classify | test | other

    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    total_tokens: Mapped[int] = mapped_column(default=0)
    usd_cost: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int] = mapped_column(default=0)

    status: Mapped[str] = mapped_column(String(16))  # ok | refused | error | over_budget
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_llm_calls_project_created", "project_id", "created_at"),)
