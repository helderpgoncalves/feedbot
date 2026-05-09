"""Billing-specific runtime settings.

Kept separate from ``feedbot_core.settings.CoreSettings`` so that:

  1. Importing the billing package never forces a CoreSettings instantiation
     in environments that don't want it (workers, CLI tools, tests).
  2. Self-host code paths can short-circuit on a single env-var read instead
     of pulling in the whole settings model.
"""

import os


def is_billing_enabled() -> bool:
    """Return True when ``FEEDBOT_BILLING_ENABLED`` is truthy.

    Truthy values: ``true``, ``TRUE``, ``1``, ``yes``. Everything else
    (including unset) returns False — that's the self-host default and
    the cloud-free-beta default.
    """
    raw = os.environ.get("FEEDBOT_BILLING_ENABLED", "").strip().lower()
    return raw in ("true", "1", "yes")


def stripe_secret_key() -> str | None:
    """The Stripe API secret. ``None`` when not configured.

    The Stripe client wrapper raises if it's called while this is unset
    AND billing is enabled — that combination is a misconfiguration we
    want to surface loudly, not paper over.
    """
    return os.environ.get("FEEDBOT_STRIPE_SECRET_KEY") or None


def stripe_webhook_secret() -> str | None:
    """The signing secret for Stripe webhooks (whsec_...).

    Used by the webhook route to verify incoming requests. Without it we
    refuse to dispatch any event — a missing secret in production is a
    fail-closed condition.
    """
    return os.environ.get("FEEDBOT_STRIPE_WEBHOOK_SECRET") or None


def stripe_price_id(plan_key: str) -> str | None:
    """Return the Stripe Price ID for a given plan key.

    We resolve via env vars rather than hard-coding because Stripe live-
    vs-test prices differ and we don't want to ship test IDs in code.

        FEEDBOT_STRIPE_PRICE_PRO=price_1...
        FEEDBOT_STRIPE_PRICE_TEAM=price_1...

    Free isn't a Stripe price (no charge); ``None`` here is a contract
    the caller must respect — never pass a None to Stripe.
    """
    if plan_key == "free" or plan_key == "self_host":
        return None
    env_var = f"FEEDBOT_STRIPE_PRICE_{plan_key.upper()}"
    return os.environ.get(env_var) or None


def stripe_trial_days() -> int:
    """Trial length applied to fresh signups when billing is enabled.

    14 days is the C2 launch default and matches what the TODO promises
    in the decision log. Single env var so we can run a 7-day trial during
    a marketing push without redeploying code.
    """
    raw = os.environ.get("FEEDBOT_STRIPE_TRIAL_DAYS", "").strip()
    if not raw:
        return 14
    try:
        return max(0, int(raw))
    except ValueError:
        return 14
