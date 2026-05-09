"""Async Stripe client wrapper.

Single chokepoint between our code and the Stripe SDK. Every Stripe call
the rest of Feedbot makes goes through one of the helpers in this module
so we can:

  - Default to ``HTTPXClient`` for true async (avoids blocking the
    asyncio event loop on the sync ``requests`` transport).
  - Lazy-initialise the client and verify env vars on first call. Apps
    that import ``feedbot_core.billing`` but never call into Stripe
    (self-host, cloud free-beta) pay zero startup cost.
  - Refuse loudly when ``FEEDBOT_BILLING_ENABLED=false`` — touching this
    module from a self-host code path is always a programming bug.
  - Re-raise SDK exceptions as ``StripeError`` so routes can catch one
    type without leaking concrete Stripe exception classes upstream.

The Stripe SDK is API-version-pinned implicitly by the package version we
ship (see pyproject.toml); avoid setting ``api_version`` here so that
upgrades land via dep bumps and never via stale pinned strings.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

# Stripe import is intentionally module-level: SDK init is cheap (no I/O,
# no network) and lru_cache + None-checks keep the actual ``StripeClient``
# instantiation lazy. The package is always installed (see pyproject); we
# only branch on whether to *use* it.
import stripe
from stripe import HTTPXClient, StripeClient, Webhook
from stripe._error import SignatureVerificationError, StripeError

from feedbot_core.billing.settings import (
    is_billing_enabled,
    stripe_secret_key,
    stripe_webhook_secret,
)

log = logging.getLogger("feedbot.billing.stripe")


class BillingMisconfigured(RuntimeError):
    """Raised when billing is supposed to be on but Stripe isn't wired up."""


@lru_cache(maxsize=1)
def get_client() -> StripeClient:
    """Return a process-singleton ``StripeClient`` configured for async I/O.

    Lazy: only constructed on first call. Cached: subsequent calls reuse
    the same client (and therefore the same HTTPX connection pool).

    Raises:
        BillingMisconfigured: When billing is disabled, or when billing
            is enabled but ``FEEDBOT_STRIPE_SECRET_KEY`` is not set. We
            fail loudly because a "soft 500" on a Stripe call is much
            harder to debug post-hoc than a clear startup error.
    """
    if not is_billing_enabled():
        raise BillingMisconfigured(
            "Stripe client requested while FEEDBOT_BILLING_ENABLED is unset/false. "
            "This is a programming error — guard the call site with is_billing_enabled()."
        )
    secret = stripe_secret_key()
    if not secret:
        raise BillingMisconfigured(
            "FEEDBOT_BILLING_ENABLED=true but FEEDBOT_STRIPE_SECRET_KEY is not set."
        )
    return StripeClient(secret, http_client=HTTPXClient())


# ─── Customer ───────────────────────────────────────────────────────────────


async def create_customer(
    *,
    email: str,
    tenant_id: int,
    name: str | None = None,
    idempotency_key: str | None = None,
) -> Any:
    """Create a Stripe customer linked to a tenant.

    The ``metadata.tenant_id`` lets us recover the mapping in webhooks
    even if our own DB row is briefly out of sync.

    ``idempotency_key`` is required when the caller is a webhook or
    signup retry path — Stripe will return the same customer instead
    of creating duplicates.
    """
    client = get_client()
    return await client.v1.customers.create_async(
        params={
            "email": email,
            "name": name or email,
            "metadata": {"tenant_id": str(tenant_id)},
        },
        options={"idempotency_key": idempotency_key} if idempotency_key else None,
    )


# ─── Subscription lifecycle ────────────────────────────────────────────────


async def create_subscription(
    *,
    customer_id: str,
    price_id: str,
    trial_period_days: int | None = None,
    idempotency_key: str | None = None,
) -> Any:
    """Create a recurring subscription on a customer.

    Uses ``payment_behavior=default_incomplete`` so an unpaid first
    invoice doesn't auto-charge — the SPA opens Stripe Checkout to
    collect the card. ``save_default_payment_method=on_subscription``
    means the card from Checkout is reused for renewals automatically.
    """
    client = get_client()
    params: dict[str, Any] = {
        "customer": customer_id,
        "items": [{"price": price_id}],
        "payment_behavior": "default_incomplete",
        "payment_settings": {
            "save_default_payment_method": "on_subscription"
        },
        "expand": ["latest_invoice.payment_intent"],
    }
    if trial_period_days and trial_period_days > 0:
        params["trial_period_days"] = trial_period_days
    return await client.v1.subscriptions.create_async(
        params=params,
        options={"idempotency_key": idempotency_key} if idempotency_key else None,
    )


async def cancel_subscription(
    subscription_id: str,
    *,
    at_period_end: bool = True,
) -> Any:
    """Cancel a subscription. Default is "at period end" so the customer
    keeps access for the time they've already paid for.
    """
    client = get_client()
    if at_period_end:
        return await client.v1.subscriptions.update_async(
            subscription_id,
            params={"cancel_at_period_end": True},
        )
    return await client.v1.subscriptions.cancel_async(subscription_id)


async def update_subscription_plan(
    subscription_id: str,
    *,
    item_id: str,
    new_price_id: str,
) -> Any:
    """Switch a subscription to a different price (i.e. plan change).

    ``proration_behavior=create_prorations`` charges/credits the
    customer for the partial period at the old price.
    """
    client = get_client()
    return await client.v1.subscriptions.update_async(
        subscription_id,
        params={
            "items": [{"id": item_id, "price": new_price_id}],
            "proration_behavior": "create_prorations",
        },
    )


# ─── Customer Portal + Checkout ────────────────────────────────────────────


async def create_portal_session(
    *,
    customer_id: str,
    return_url: str,
) -> Any:
    """Stripe-hosted self-service billing portal.

    The return URL is where Stripe sends the user after they hit "back"
    on the portal — typically our own ``/billing`` page.
    """
    client = get_client()
    return await client.v1.billing_portal.sessions.create_async(
        params={"customer": customer_id, "return_url": return_url},
    )


async def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    trial_period_days: int | None = None,
    idempotency_key: str | None = None,
) -> Any:
    """Stripe-hosted checkout for a subscription.

    Used by the SPA "Upgrade to Pro" flow when the customer has not yet
    entered a card. Stripe owns the form; we just redirect the browser
    to ``session.url`` and trust the webhook to update our DB on success.
    """
    client = get_client()
    params: dict[str, Any] = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if trial_period_days and trial_period_days > 0:
        params["subscription_data"] = {"trial_period_days": trial_period_days}
    return await client.v1.checkout.sessions.create_async(
        params=params,
        options={"idempotency_key": idempotency_key} if idempotency_key else None,
    )


# ─── Webhook signature verification ────────────────────────────────────────


def verify_webhook(payload: bytes | str, sig_header: str) -> Any:
    """Validate a Stripe webhook signature and return the parsed event.

    Synchronous because ``Webhook.construct_event`` is pure CPU (HMAC).
    Caller is the FastAPI route handler, which itself is async — running
    a few hundred microseconds of HMAC inline doesn't move the needle.

    Raises:
        BillingMisconfigured: When ``FEEDBOT_STRIPE_WEBHOOK_SECRET`` is
            missing. Fail-closed: a Stripe event arriving without a
            configured secret means an attacker could forge events.
        SignatureVerificationError: When the signature doesn't match.
            Routes should map this to HTTP 400.
        ValueError: Malformed payload (non-JSON, etc.) — also 400.
    """
    secret = stripe_webhook_secret()
    if not secret:
        raise BillingMisconfigured(
            "FEEDBOT_STRIPE_WEBHOOK_SECRET is not set; refusing to process webhooks."
        )
    payload_str = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    return Webhook.construct_event(
        payload_str,
        sig_header,
        secret,
    )


# Re-export the SDK exception types so callers don't need a `stripe`
# import. Keeps the surface area to "import from feedbot_core.billing".
__all__ = [
    "BillingMisconfigured",
    "SignatureVerificationError",
    "StripeError",
    "cancel_subscription",
    "create_checkout_session",
    "create_customer",
    "create_portal_session",
    "create_subscription",
    "get_client",
    "update_subscription_plan",
    "verify_webhook",
]


# Quiet a "unused module-level import" lint when stripe is only used for
# its exported types: confirm the symbol is reachable at import time.
_ = stripe
