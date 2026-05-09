"""Billing primitives — quota enforcement and plan limits.

This package is **deliberately decoupled** from Stripe. Stripe lives in
``feedbot_core.billing.stripe_client`` (added in phase C2). The pieces in
this top-level module are safe to import and call from anywhere — they
no-op cleanly when ``FEEDBOT_BILLING_ENABLED`` is unset/false (the
self-host default).

Import contract:
    from feedbot_core.billing import assert_quota, current_plan
    from feedbot_core.billing import is_billing_enabled, QuotaExceeded
"""

from feedbot_core.billing.plans import (
    PLANS,
    Plan,
    QuotaKind,
    current_plan,
)
from feedbot_core.billing.quota import (
    QuotaExceeded,
    assert_quota,
)
from feedbot_core.billing.settings import is_billing_enabled

__all__ = [
    "PLANS",
    "Plan",
    "QuotaKind",
    "QuotaExceeded",
    "assert_quota",
    "current_plan",
    "is_billing_enabled",
]
