import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_core.ids import new_api_key, new_feedback_id
from feedbot_core.models import (
    ApiKey,
    ChatLink,
    ChatLinkToken,
    Feedback,
    FeedbackStatus,
    FeedbackType,
    MagicLinkToken,
    Project,
    Severity,
    Tenant,
    User,
)
from feedbot_core.security import hash_secret, verify_secret


# ─── Tenants & users ────────────────────────────────────────────────────────


async def get_or_create_user(session: AsyncSession, email: str) -> User:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user:
        return user
    tenant = Tenant(name=email.split("@")[0])
    session.add(tenant)
    await session.flush()
    user = User(email=email, tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    return user


# ─── Projects ───────────────────────────────────────────────────────────────


async def list_projects(session: AsyncSession, tenant_id: int) -> list[Project]:
    rows = await session.execute(
        select(Project).where(Project.tenant_id == tenant_id).order_by(Project.created_at.desc())
    )
    return list(rows.scalars())


async def create_project(session: AsyncSession, tenant_id: int, slug: str, name: str) -> Project:
    project = Project(tenant_id=tenant_id, slug=slug, name=name)
    session.add(project)
    await session.flush()
    return project


# ─── API keys ───────────────────────────────────────────────────────────────


async def issue_api_key(
    session: AsyncSession, project_id: int, label: str, scope: str = "write"
) -> tuple[ApiKey, str]:
    full, prefix = new_api_key()
    key = ApiKey(
        project_id=project_id,
        label=label,
        prefix=prefix,
        secret_hash=hash_secret(full),
        scope=scope,
    )
    session.add(key)
    await session.flush()
    return key, full


async def authenticate_api_key(session: AsyncSession, raw: str) -> ApiKey | None:
    if not raw or not raw.startswith("fbk_"):
        return None
    # Format: fbk_<env>_<urlsafe-secret>; prefix stored = "fbk_<env>_" + first 8 chars of secret.
    parts = raw.split("_", 2)
    if len(parts) != 3 or len(parts[2]) < 8:
        return None
    prefix = f"{parts[0]}_{parts[1]}_{parts[2][:8]}"
    candidate = (
        await session.execute(select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None)))
    ).scalar_one_or_none()
    if not candidate:
        return None
    if not verify_secret(raw, candidate.secret_hash):
        return None
    candidate.last_used_at = datetime.now(timezone.utc)
    return candidate


# ─── Chat links ─────────────────────────────────────────────────────────────


async def project_for_chat(session: AsyncSession, platform: str, chat_id: str) -> Project | None:
    row = await session.execute(
        select(Project)
        .join(ChatLink, ChatLink.project_id == Project.id)
        .where(ChatLink.platform == platform, ChatLink.chat_id == chat_id)
    )
    return row.scalar_one_or_none()


async def link_chat(
    session: AsyncSession, project_id: int, platform: str, chat_id: str, title: str | None
) -> ChatLink:
    link = ChatLink(project_id=project_id, platform=platform, chat_id=chat_id, title=title)
    session.add(link)
    await session.flush()
    return link


async def list_chat_links(session: AsyncSession, project_id: int) -> list[ChatLink]:
    rows = await session.execute(
        select(ChatLink)
        .where(ChatLink.project_id == project_id)
        .order_by(ChatLink.created_at.desc())
    )
    return list(rows.scalars())


async def unlink_chat(session: AsyncSession, project_id: int, link_id: int) -> bool:
    link = await session.get(ChatLink, link_id)
    if not link or link.project_id != project_id:
        return False
    await session.delete(link)
    await session.flush()
    return True


# ─── Chat link tokens (deep-link onboarding) ────────────────────────────────


async def issue_chat_link_token(
    session: AsyncSession, project_id: int, created_by_email: str, ttl_minutes: int = 15
) -> ChatLinkToken:
    token = ChatLinkToken(
        project_id=project_id,
        token=secrets.token_urlsafe(24),
        created_by_email=created_by_email,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    )
    session.add(token)
    await session.flush()
    return token


async def redeem_chat_link_token(
    session: AsyncSession, raw_token: str, platform: str, chat_id: str, chat_title: str | None
) -> ChatLink | None:
    """Atomically: validate token, create chat_links row, mark token used.

    Returns the new ChatLink, or None if token invalid/expired/used or chat already linked.
    """
    row = await session.execute(
        select(ChatLinkToken).where(ChatLinkToken.token == raw_token)
    )
    token = row.scalar_one_or_none()
    if not token or token.used_at is not None:
        return None
    if token.expires_at < datetime.now(timezone.utc):
        return None

    # Refuse if this chat is already linked anywhere (UNIQUE would block, but we want
    # a clean error path).
    existing = await project_for_chat(session, platform, chat_id)
    if existing:
        return None

    link = ChatLink(
        project_id=token.project_id, platform=platform, chat_id=chat_id, title=chat_title
    )
    session.add(link)
    token.used_at = datetime.now(timezone.utc)
    token.used_chat_id = chat_id
    await session.flush()
    return link


# ─── Feedbacks ──────────────────────────────────────────────────────────────


async def create_feedback(
    session: AsyncSession,
    *,
    project_id: int,
    title: str,
    body: str,
    type: FeedbackType = FeedbackType.OTHER,
    severity: Severity = Severity.MEDIUM,
    author_platform: str = "web",
    author_id: str = "",
    author_name: str | None = None,
) -> Feedback:
    fb = Feedback(
        public_id=new_feedback_id(),
        project_id=project_id,
        title=title,
        body=body,
        type=type,
        severity=severity,
        author_platform=author_platform,
        author_id=author_id,
        author_name=author_name,
    )
    session.add(fb)
    await session.flush()
    return fb


async def get_feedback_by_public_id(
    session: AsyncSession, project_id: int, public_id: str
) -> Feedback | None:
    row = await session.execute(
        select(Feedback).where(Feedback.project_id == project_id, Feedback.public_id == public_id)
    )
    return row.scalar_one_or_none()


async def list_feedbacks(
    session: AsyncSession,
    project_id: int,
    *,
    status: FeedbackStatus | None = None,
    type: FeedbackType | None = None,
    severity: Severity | None = None,
    limit: int = 50,
) -> list[Feedback]:
    q = select(Feedback).where(Feedback.project_id == project_id)
    if status:
        q = q.where(Feedback.status == status)
    if type:
        q = q.where(Feedback.type == type)
    if severity:
        q = q.where(Feedback.severity == severity)
    q = q.order_by(Feedback.created_at.desc()).limit(limit)
    rows = await session.execute(q)
    return list(rows.scalars())


async def update_feedback_status(
    session: AsyncSession, feedback: Feedback, status: FeedbackStatus, note: str | None = None
) -> Feedback:
    feedback.status = status
    if note:
        feedback.note = (feedback.note + "\n" if feedback.note else "") + note
    await session.flush()
    return feedback


async def stats_for_project(session: AsyncSession, project_id: int) -> dict[str, int]:
    rows = await session.execute(
        select(Feedback.status, func.count())
        .where(Feedback.project_id == project_id)
        .group_by(Feedback.status)
    )
    out = {s.value: 0 for s in FeedbackStatus}
    for status, count in rows:
        out[str(status)] = count
    return out


# ─── Magic link tokens ──────────────────────────────────────────────────────


async def issue_magic_link(session: AsyncSession, email: str, raw_token: str, ttl_minutes: int = 15) -> None:
    token = MagicLinkToken(
        email=email,
        token_hash=hash_secret(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    )
    session.add(token)
    await session.flush()


async def consume_magic_link(session: AsyncSession, email: str, raw_token: str) -> bool:
    rows = await session.execute(
        select(MagicLinkToken)
        .where(MagicLinkToken.email == email, MagicLinkToken.used_at.is_(None))
        .order_by(MagicLinkToken.created_at.desc())
        .limit(5)
    )
    now = datetime.now(timezone.utc)
    for token in rows.scalars():
        if token.expires_at < now:
            continue
        if verify_secret(raw_token, token.token_hash):
            token.used_at = now
            return True
    return False
