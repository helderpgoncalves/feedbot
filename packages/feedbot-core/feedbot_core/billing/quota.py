"""Quota enforcement.

Single entry point: ``assert_quota(session, tenant_id, kind)``. Designed
to be called from hot paths (``POST /v1/projects``, ``/v1/internal/ingest``,
member adds, invites) without a perf cost on self-host:

  - When billing is disabled (``FEEDBOT_BILLING_ENABLED`` unset/false), the
    function returns immediately. **No DB query, no plan lookup, no row
    construction.** This is the only path self-host ever takes.
  - When billing is enabled, we read the tenant's ``Subscription`` row,
    resolve the plan, count current usage, and raise ``QuotaExceeded``
    when over.

We deliberately query usage on the fly rather than caching it. The plans
have small numbers (5 projects, 1000 feedback/mo) and the queries are
indexed; correctness > caching at this scale. A counter on the Subscription
row (``monthly_feedback_count``) is incremented inline by the ingest path
*after* the quota check passes — that's the cheap fast path.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_core.billing.plans import QuotaKind, current_plan, limit_for
from feedbot_core.billing.settings import is_billing_enabled


class QuotaExceeded(Exception):
    """Raised when a tenant has hit a plan limit.

    The router layer is expected to translate this into HTTP 402 with a
    structured body (kind, current, limit, upgrade_url). We expose all the
    pieces as attributes so the router doesn't have to re-query.
    """

    def __init__(self, kind: QuotaKind, current: int, limit: int) -> None:
        super().__init__(
            f"quota exceeded: {kind}={current}/{limit}",
        )
        self.kind: QuotaKind = kind
        self.current: int = current
        self.limit: int = limit


async def assert_quota(
    session: AsyncSession,
    tenant_id: int,
    kind: QuotaKind,
) -> None:
    """Raise ``QuotaExceeded`` if this tenant is at or over its plan limit.

    No-op when billing is disabled. Self-hosters and cloud free-beta both
    take this branch — zero DB cost, zero side effects.
    """
    if not is_billing_enabled():
        return

    # Local import to avoid a circular at module load time
    # (models.py imports nothing from billing/, but billing/__init__.py is
    # imported by routers that also import models).
    from feedbot_core.models import (
        Feedback,
        Invite,
        Project,
        ProjectMember,
        Subscription,
        User,
    )

    sub_row = await session.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    sub = sub_row.scalar_one_or_none()
    plan = current_plan(sub.plan if sub is not None else None)
    limit = limit_for(plan, kind)
    if limit is None:
        # Unlimited tier (Team or self-host pseudo-plan) — never blocks.
        return

    if kind == "project":
        count_row = await session.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.tenant_id == tenant_id)
        )
        current = count_row.scalar_one()
    elif kind == "feedback":
        # Use the rolling monthly counter on Subscription. The counter is
        # incremented by the ingest path inside the same transaction, and
        # reset by the Stripe ``invoice.payment_succeeded`` webhook (C2.3).
        current = sub.monthly_feedback_count if sub is not None else 0
    elif kind == "member":
        # Active members + pending invites. We count both because an
        # admin who invites 100 people but doesn't have them accept yet
        # has effectively reserved 100 seats.
        active_row = await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.tenant_id == tenant_id)
        )
        pending_row = await session.execute(
            select(func.count())
            .select_from(Invite)
            .where(Invite.tenant_id == tenant_id, Invite.used_at.is_(None))
        )
        current = active_row.scalar_one() + pending_row.scalar_one()
    else:
        raise ValueError(f"unknown quota kind: {kind!r}")

    if current >= limit:
        raise QuotaExceeded(kind=kind, current=current, limit=limit)


__all__ = ["QuotaExceeded", "assert_quota"]
