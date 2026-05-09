"""Static plan definitions.

These are intentionally a Python dict, not a DB table:

  - Plans rarely change, and when they do, they need a code review and a
    deploy — not a DB write from someone with admin access.
  - Pricing tweaks during pre-launch are one-line changes here.
  - Self-host bundles never reference these (``assert_quota`` short-circuits
    before plan lookup), so the dict has zero cost in the self-host bundle.

Stripe price IDs are resolved separately in ``stripe_client.py`` (phase C2).
"""

from dataclasses import dataclass
from typing import Literal

QuotaKind = Literal["project", "feedback", "member"]


@dataclass(frozen=True)
class Plan:
    """A single subscription tier.

    ``unlimited`` semantics: when a limit is ``None``, ``assert_quota`` lets
    every request through. We use ``None`` (not a sentinel like -1) so the
    type checker catches accidental arithmetic.
    """

    key: str
    display_name: str
    monthly_price_cents: int
    project_limit: int | None
    monthly_feedback_limit: int | None
    member_limit: int | None


# Cloud-only plans. The "self_host" pseudo-plan is returned by
# `current_plan` when billing is disabled — it has no limits and lives only
# in code, never in the DB.
PLANS: dict[str, Plan] = {
    "free": Plan(
        key="free",
        display_name="Free",
        monthly_price_cents=0,
        project_limit=1,
        monthly_feedback_limit=100,
        member_limit=2,
    ),
    "pro": Plan(
        key="pro",
        display_name="Pro",
        monthly_price_cents=900,
        project_limit=5,
        monthly_feedback_limit=1000,
        member_limit=10,
    ),
    "team": Plan(
        key="team",
        display_name="Team",
        monthly_price_cents=2900,
        project_limit=None,
        monthly_feedback_limit=None,
        member_limit=None,
    ),
}


SELF_HOST_PLAN = Plan(
    key="self_host",
    display_name="Self-hosted",
    monthly_price_cents=0,
    project_limit=None,
    monthly_feedback_limit=None,
    member_limit=None,
)


def current_plan(plan_key: str | None) -> Plan:
    """Resolve a plan key to a ``Plan`` instance.

    Falls back to ``free`` when the key is unknown — never raises, because
    quota enforcement should never crash an ingest path. Unknown keys are
    a sign of a stale row written before a plan was renamed; treating them
    as Free is the safest direction (might block a write but won't leak
    paid limits).
    """
    if plan_key is None:
        return SELF_HOST_PLAN
    return PLANS.get(plan_key, PLANS["free"])


def limit_for(plan: Plan, kind: QuotaKind) -> int | None:
    """Return the numeric limit on this plan for a given quota kind."""
    if kind == "project":
        return plan.project_limit
    if kind == "feedback":
        return plan.monthly_feedback_limit
    if kind == "member":
        return plan.member_limit
    raise ValueError(f"unknown quota kind: {kind!r}")
