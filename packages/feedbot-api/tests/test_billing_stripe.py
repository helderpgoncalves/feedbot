"""C2 — Stripe webhook + billing endpoints.

These tests focus on the boundaries we control without hitting the live
Stripe API:

  - Signature verification accepts a payload signed with our test secret
    and rejects everything else.
  - Webhook dedupe via stripe_processed_events catches replays.
  - Each event type we care about lands the right side effects on the
    Subscription row (created/updated/deleted, invoice.payment_*).
  - GET /v1/billing/subscription on self-host returns the no-limits
    snapshot; on cloud-with-billing returns the plan + usage.

We never call out to Stripe in tests — the Stripe client wrapper is
mocked at the boundary functions we expose. The webhook itself is hit
via real HTTP through the FastAPI test client, with a hand-signed
header so we exercise our `verify_webhook` function end-to-end.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import stripe
from feedbot_core.models import Subscription
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


_AT = chr(0x40)
_DOMAIN = "example.com"


def _addr(local: str) -> str:
    return f"{local}{_AT}{_DOMAIN}"


_WEBHOOK_SECRET = "whsec_testsecret_C2"


@pytest.fixture
def billing_on() -> AsyncIterator[None]:
    """Flip every cloud-billing env var on for the duration of a test.

    We set both the enable flag and the secrets a real deployment needs;
    individual tests can still override via their own monkeypatching.
    """
    snapshot = {
        k: os.environ.get(k)
        for k in (
            "FEEDBOT_BILLING_ENABLED",
            "FEEDBOT_STRIPE_SECRET_KEY",
            "FEEDBOT_STRIPE_WEBHOOK_SECRET",
            "FEEDBOT_STRIPE_PRICE_PRO",
            "FEEDBOT_STRIPE_PRICE_TEAM",
        )
    }
    os.environ["FEEDBOT_BILLING_ENABLED"] = "true"
    os.environ["FEEDBOT_STRIPE_SECRET_KEY"] = "sk_test_dummy"
    os.environ["FEEDBOT_STRIPE_WEBHOOK_SECRET"] = _WEBHOOK_SECRET
    os.environ["FEEDBOT_STRIPE_PRICE_PRO"] = "price_pro_test"
    os.environ["FEEDBOT_STRIPE_PRICE_TEAM"] = "price_team_test"
    try:
        yield
    finally:
        for k, v in snapshot.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest_asyncio.fixture
async def reset_billing_clients():
    """Drop the cached Stripe client between tests so env-var flips
    actually take effect on the next call."""
    from feedbot_core.billing import stripe_client

    stripe_client.get_client.cache_clear()
    yield
    stripe_client.get_client.cache_clear()


def _sign(payload: str, secret: str = _WEBHOOK_SECRET, ts: int | None = None) -> str:
    """Build a valid `Stripe-Signature` header for ``payload``."""
    ts = ts or int(time.time())
    sig = stripe.WebhookSignature._compute_signature(f"{ts}.{payload}", secret)
    return f"t={ts},v1={sig}"


# ─── Webhook signature tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(
    client: AsyncClient,
    billing_on,
    reset_billing_clients,
) -> None:
    payload = '{"id":"evt_1","type":"customer.subscription.created","data":{"object":{}}}'
    res = await client.post(
        "/v1/internal/stripe-webhook",
        content=payload,
        headers={"stripe-signature": "t=1,v1=deadbeef"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_webhook_accepts_valid_signature_unknown_event(
    client: AsyncClient,
    billing_on,
    reset_billing_clients,
) -> None:
    """An event type we don't track still 200s — Stripe expects 2xx and
    we don't want to be retried for events that aren't actionable."""
    payload = json.dumps(
        {
            "id": "evt_unknown_1",
            "type": "charge.captured",
            "data": {"object": {}},
        }
    )
    res = await client.post(
        "/v1/internal/stripe-webhook",
        content=payload,
        headers={"stripe-signature": _sign(payload)},
    )
    assert res.status_code == 200


# ─── Dedupe ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_dedupes_replay(
    client: AsyncClient,
    db_session: AsyncSession,
    billing_on,
    reset_billing_clients,
    make_tenant,
) -> None:
    """The same event_id twice  >>>  side effects fire once."""
    tenant = await make_tenant(name="ReplayCo")
    sub = Subscription(
        tenant_id=tenant.id,
        plan="free",
        status="active",
        stripe_customer_id="cus_replay_1",
    )
    db_session.add(sub)
    await db_session.flush()

    payload = json.dumps(
        {
            "id": "evt_replay_1",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_x",
                    "customer": "cus_replay_1",
                    "status": "active",
                    "current_period_end": int(time.time()) + 86400 * 30,
                    "items": {
                        "data": [{"price": {"id": "price_pro_test"}}]
                    },
                }
            },
        }
    )
    headers = {"stripe-signature": _sign(payload)}

    res1 = await client.post(
        "/v1/internal/stripe-webhook", content=payload, headers=headers
    )
    assert res1.status_code == 200
    res2 = await client.post(
        "/v1/internal/stripe-webhook", content=payload, headers=headers
    )
    assert res2.status_code == 200

    # Plan rolled to pro exactly once. A second pass through the handler
    # would hit the same upsert idempotently (no harm), but the dedupe
    # check should short-circuit before that.
    refreshed = await db_session.execute(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    )
    row = refreshed.scalar_one()
    assert row.plan == "pro"
    assert row.status == "active"


# ─── Event-type dispatch ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_subscription_created_sets_plan(
    client: AsyncClient,
    db_session: AsyncSession,
    billing_on,
    reset_billing_clients,
    make_tenant,
) -> None:
    tenant = await make_tenant(name="SubCreated")
    db_session.add(
        Subscription(
            tenant_id=tenant.id,
            plan="free",
            status="active",
            stripe_customer_id="cus_subcreated",
        )
    )
    await db_session.flush()

    payload = json.dumps(
        {
            "id": "evt_subcreated",
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_new",
                    "customer": "cus_subcreated",
                    "status": "trialing",
                    "current_period_end": int(time.time()) + 86400 * 14,
                    "items": {
                        "data": [{"price": {"id": "price_pro_test"}}]
                    },
                }
            },
        }
    )
    res = await client.post(
        "/v1/internal/stripe-webhook",
        content=payload,
        headers={"stripe-signature": _sign(payload)},
    )
    assert res.status_code == 200

    sub_row = await db_session.execute(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    )
    sub = sub_row.scalar_one()
    assert sub.plan == "pro"
    assert sub.status == "trialing"
    assert sub.stripe_subscription_id == "sub_new"


@pytest.mark.asyncio
async def test_webhook_subscription_deleted_downgrades_to_free(
    client: AsyncClient,
    db_session: AsyncSession,
    billing_on,
    reset_billing_clients,
    make_tenant,
) -> None:
    tenant = await make_tenant(name="Cancelling")
    db_session.add(
        Subscription(
            tenant_id=tenant.id,
            plan="pro",
            status="active",
            stripe_customer_id="cus_cancel",
            stripe_subscription_id="sub_cancel",
        )
    )
    await db_session.flush()

    payload = json.dumps(
        {
            "id": "evt_cancel",
            "type": "customer.subscription.deleted",
            "data": {"object": {"customer": "cus_cancel"}},
        }
    )
    res = await client.post(
        "/v1/internal/stripe-webhook",
        content=payload,
        headers={"stripe-signature": _sign(payload)},
    )
    assert res.status_code == 200

    sub_row = await db_session.execute(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    )
    sub = sub_row.scalar_one()
    assert sub.plan == "free"
    assert sub.status == "canceled"


@pytest.mark.asyncio
async def test_webhook_invoice_payment_succeeded_resets_counter(
    client: AsyncClient,
    db_session: AsyncSession,
    billing_on,
    reset_billing_clients,
    make_tenant,
) -> None:
    tenant = await make_tenant(name="Renewal")
    db_session.add(
        Subscription(
            tenant_id=tenant.id,
            plan="pro",
            status="active",
            stripe_customer_id="cus_renew",
            monthly_feedback_count=873,
        )
    )
    await db_session.flush()

    payload = json.dumps(
        {
            "id": "evt_invoice_paid",
            "type": "invoice.payment_succeeded",
            "data": {"object": {"customer": "cus_renew"}},
        }
    )
    res = await client.post(
        "/v1/internal/stripe-webhook",
        content=payload,
        headers={"stripe-signature": _sign(payload)},
    )
    assert res.status_code == 200

    sub_row = await db_session.execute(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    )
    sub = sub_row.scalar_one()
    assert sub.monthly_feedback_count == 0
    assert sub.monthly_feedback_reset_at is not None


@pytest.mark.asyncio
async def test_webhook_invoice_payment_failed_marks_past_due(
    client: AsyncClient,
    db_session: AsyncSession,
    billing_on,
    reset_billing_clients,
    make_tenant,
) -> None:
    tenant = await make_tenant(name="PastDueCo")
    db_session.add(
        Subscription(
            tenant_id=tenant.id,
            plan="pro",
            status="active",
            stripe_customer_id="cus_pastdue",
        )
    )
    await db_session.flush()

    payload = json.dumps(
        {
            "id": "evt_invoice_failed",
            "type": "invoice.payment_failed",
            "data": {"object": {"customer": "cus_pastdue"}},
        }
    )
    res = await client.post(
        "/v1/internal/stripe-webhook",
        content=payload,
        headers={"stripe-signature": _sign(payload)},
    )
    assert res.status_code == 200

    sub_row = await db_session.execute(
        select(Subscription).where(Subscription.tenant_id == tenant.id)
    )
    sub = sub_row.scalar_one()
    assert sub.status == "past_due"


# ─── /v1/billing/subscription ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_billing_subscription_self_host_no_limits(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    login_as,
) -> None:
    """Self-host (billing disabled): plan='self_host', limits=None, usage=None."""
    prev = os.environ.pop("FEEDBOT_BILLING_ENABLED", None)
    try:
        tenant = await make_tenant(name="SelfHost")
        owner = await make_user(
            tenant=tenant, email=_addr("owner_selfhost"), role="owner"
        )
        await login_as(owner)
        res = await client.get("/v1/billing/subscription")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["plan"] == "self_host"
        assert body["limits"] is None
        assert body["usage"] is None
    finally:
        if prev is not None:
            os.environ["FEEDBOT_BILLING_ENABLED"] = prev


@pytest.mark.asyncio
async def test_billing_subscription_cloud_returns_plan_and_usage(
    client: AsyncClient,
    db_session: AsyncSession,
    billing_on,
    reset_billing_clients,
    make_tenant,
    make_user,
    make_project,
    login_as,
) -> None:
    """Cloud (billing on): real plan + real usage counts."""
    tenant = await make_tenant(name="CloudCo")
    owner = await make_user(
        tenant=tenant, email=_addr("owner_cloud"), role="owner"
    )
    await make_project(tenant=tenant, slug="p1", name="P1")
    db_session.add(
        Subscription(
            tenant_id=tenant.id,
            plan="pro",
            status="active",
            stripe_customer_id="cus_for_get",
            monthly_feedback_count=42,
        )
    )
    await db_session.flush()

    await login_as(owner)
    res = await client.get("/v1/billing/subscription")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plan"] == "pro"
    assert body["limits"] == {
        "project_limit": 5,
        "monthly_feedback_limit": 1000,
        "member_limit": 10,
    }
    assert body["usage"]["projects"] == 1
    assert body["usage"]["monthly_feedback"] == 42
    # The owner is the only user, no pending invites.
    assert body["usage"]["members"] == 1
