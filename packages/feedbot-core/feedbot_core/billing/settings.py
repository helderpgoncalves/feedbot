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
