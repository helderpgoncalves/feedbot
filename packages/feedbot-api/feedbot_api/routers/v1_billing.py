"""Billing endpoints — Stripe webhook, subscription state, portal, checkout.

The webhook is a peer of the bot's ``/v1/internal/*`` endpoints (authn'd
by signature, not by user/session) but lives here for cohesion with the
billing surface. The auth'd endpoints are owner-only and fail-closed when
``billingEnabled`` is false on the deployment.

All routes return JSON. The webhook always returns 200 (Stripe retries on
non-2xx) — if we can't process an event we still ack and log; the dedupe
table keeps the next replay safe.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from feedbot_core.billing import (
    PLANS,
    Plan,
    QuotaExceeded,
    assert_quota,
    current_plan,
    is_billing_enabled,
)
from feedbot_core.billing.plans import SELF_HOST_PLAN
from feedbot_core.billing.settings import (
    stripe_price_id,
    stripe_trial_days,
)
from feedbot_core.models import Invite, Project, Subscription, Tenant, User
from feedbot_core.repos import (
    ensure_subscription,
    get_subscription_by_stripe_customer,
    get_subscription_for_tenant,
    mark_stripe_event_processed,
    reset_monthly_counters_if_due,
    stripe_event_already_processed,
    update_subscription_from_stripe,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session, require_owner, require_user
from feedbot_api.schemas import (
    BillingLimits,
    BillingUsage,
    CheckoutIn,
    CheckoutOut,
    PortalOut,
    SubscriptionOut,
)

log = logging.getLogger("feedbot.billing")

router = APIRouter(prefix="/v1", tags=["v1.billing"])


# ─── Helpers ────────────────────────────────────────────────────────────────


def _public_url() -> str:
    """The deployment's external URL — used to build Checkout return links.

    Falls back to localhost so dev defaults Just Work without env config.
    """
    return os.environ.get("FEEDBOT_PUBLIC_URL", "").rstrip("/") or "http://localhost:3000"


async def _usage_for(session: AsyncSession, tenant_id: int) -> BillingUsage:
    """Count current resource usage for a tenant. Cheap — three indexed COUNT(*)s."""
    proj_row = await session.execute(
        select(func.count())
        .select_from(Project)
        .where(Project.tenant_id == tenant_id)
    )
    user_row = await session.execute(
        select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
    )
    pending_row = await session.execute(
        select(func.count())
        .select_from(Invite)
        .where(Invite.tenant_id == tenant_id, Invite.used_at.is_(None))
    )
    sub = await get_subscription_for_tenant(session, tenant_id)
    monthly = sub.monthly_feedback_count if sub is not None else 0
    return BillingUsage(
        projects=proj_row.scalar_one(),
        monthly_feedback=monthly,
        members=user_row.scalar_one() + pending_row.scalar_one(),
    )


def _limits_from_plan(plan: Plan) -> BillingLimits:
    return BillingLimits(
        project_limit=plan.project_limit,
        monthly_feedback_limit=plan.monthly_feedback_limit,
        member_limit=plan.member_limit,
    )


# ─── GET /v1/billing/subscription ──────────────────────────────────────────


@router.get(
    "/billing/subscription",
    response_model=SubscriptionOut,
    summary="Current plan, status, and usage for the signed-in tenant",
)
async def get_subscription(
    me: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    """Returns plan + limits + usage. On self-host (billing disabled),
    surfaces ``plan='self_host'`` with no limits and no usage so the SPA
    can render an unconditional "no limits" state.
    """
    if not is_billing_enabled():
        return SubscriptionOut(
            plan=SELF_HOST_PLAN.key,
            plan_display_name=SELF_HOST_PLAN.display_name,
            status="active",
            current_period_end=None,
            trial_end=None,
            limits=None,
            usage=None,
            cancel_at_period_end=False,
        )

    sub = await get_subscription_for_tenant(session, me.tenant_id)
    plan = current_plan(sub.plan if sub is not None else None)
    return SubscriptionOut(
        plan=plan.key,
        plan_display_name=plan.display_name,
        status=sub.status if sub is not None else "active",
        current_period_end=sub.current_period_end if sub is not None else None,
        # Trial-end isn't stored separately — we mirror Stripe's status
        # ``trialing`` and let the SPA derive "X days left in trial" from
        # current_period_end. Reserved for a future column when we need
        # finer reporting.
        trial_end=None,
        limits=_limits_from_plan(plan),
        usage=await _usage_for(session, me.tenant_id),
        cancel_at_period_end=False,
    )


# ─── POST /v1/billing/portal ───────────────────────────────────────────────


@router.post(
    "/billing/portal",
    response_model=PortalOut,
    summary="Create a Stripe Customer Portal session (owner only)",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Billing not enabled."},
        status.HTTP_409_CONFLICT: {"description": "Tenant has no Stripe customer yet."},
    },
)
async def create_portal(
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> PortalOut:
    if not is_billing_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    sub = await get_subscription_for_tenant(session, me.tenant_id)
    if sub is None or not sub.stripe_customer_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no Stripe customer for this tenant — start an upgrade first",
        )

    # Local import so the Stripe SDK isn't loaded into the process for
    # routes that never reach it (e.g. self-host import-time).
    from feedbot_core.billing.stripe_client import (
        StripeError,
        create_portal_session,
    )

    return_url = f"{_public_url()}/billing"
    try:
        s = await create_portal_session(
            customer_id=sub.stripe_customer_id, return_url=return_url
        )
    except StripeError as exc:
        log.warning("portal_session_failed tenant=%s err=%s", me.tenant_id, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "stripe portal error") from exc
    return PortalOut(url=s.url)


# ─── POST /v1/billing/checkout ─────────────────────────────────────────────


@router.post(
    "/billing/checkout",
    response_model=CheckoutOut,
    summary="Create a Stripe Checkout session for an upgrade (owner only)",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Billing not enabled."},
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid plan key, or plan has no Stripe price configured."
        },
    },
)
async def create_checkout(
    body: CheckoutIn,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> CheckoutOut:
    if not is_billing_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    if body.plan not in PLANS or body.plan == "free":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid plan")

    price_id = stripe_price_id(body.plan)
    if not price_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"plan {body.plan!r} has no Stripe price configured",
        )

    # Lazy: ensure a Stripe customer exists for this tenant.
    sub = await ensure_subscription(session, me.tenant_id, plan="free")
    from feedbot_core.billing.stripe_client import (
        StripeError,
        create_checkout_session,
        create_customer,
    )

    if not sub.stripe_customer_id:
        try:
            tenant = await session.get(Tenant, me.tenant_id)
            customer = await create_customer(
                email=me.email,
                tenant_id=me.tenant_id,
                name=tenant.name if tenant else None,
                idempotency_key=f"customer-{me.tenant_id}",
            )
        except StripeError as exc:
            log.warning(
                "customer_create_failed tenant=%s err=%s", me.tenant_id, exc
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "stripe customer error"
            ) from exc
        sub.stripe_customer_id = customer.id
        await session.flush()

    base = _public_url()
    try:
        s = await create_checkout_session(
            customer_id=sub.stripe_customer_id,
            price_id=price_id,
            success_url=f"{base}/billing?upgraded=1",
            cancel_url=f"{base}/billing",
            trial_period_days=stripe_trial_days() if sub.plan == "free" else None,
            idempotency_key=f"checkout-{me.tenant_id}-{body.plan}",
        )
    except StripeError as exc:
        log.warning("checkout_failed tenant=%s err=%s", me.tenant_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "stripe checkout error"
        ) from exc
    return CheckoutOut(url=s.url)


# ─── POST /v1/internal/stripe-webhook ──────────────────────────────────────
#
# Public route (Stripe is the caller); authentication is the signed
# `Stripe-Signature` header verified inside the handler. NEVER add a
# Depends() that requires auth here.

webhook_router = APIRouter(prefix="/v1/internal", tags=["internal.stripe"])


def _ts_to_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


def _plan_from_price(price_id: str | None) -> str | None:
    """Reverse-resolve a Stripe price ID to one of our plan keys.

    We loop the env vars rather than maintaining a second mapping. Tiny
    constant-time scan — the dict has 3 entries.
    """
    if not price_id:
        return None
    for key in PLANS:
        if stripe_price_id(key) == price_id:
            return key
    return None


@webhook_router.post(
    "/stripe-webhook",
    summary="Receive Stripe webhook events (signed)",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Invalid signature or malformed payload."
        },
    },
)
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Verify the signature, dedupe by event_id, dispatch by event type.

    Returns 200 even on no-op events (Stripe retries on non-2xx). Errors
    in our own DB are logged and surface as 500 so Stripe retries; bad
    signatures are 400 (Stripe doesn't retry those).
    """
    # Lazy import — mirrors the rest of the module.
    from feedbot_core.billing.stripe_client import (
        BillingMisconfigured,
        SignatureVerificationError,
        verify_webhook,
    )

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = verify_webhook(payload, sig)
    except SignatureVerificationError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad signature")
    except (BillingMisconfigured, ValueError) as exc:
        log.error("stripe_webhook_misconfigured err=%s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "misconfigured")

    event_id: str = event["id"]
    event_type: str = event["type"]

    # Dedupe — Stripe will replay this exact event during retries.
    if await stripe_event_already_processed(session, event_id):
        log.info("stripe_event_replay event_id=%s type=%s", event_id, event_type)
        return Response(status_code=status.HTTP_200_OK)

    log.info("stripe_event event_id=%s type=%s", event_id, event_type)

    try:
        await _dispatch(session, event)
    except Exception as exc:  # pragma: no cover — fail to 500 so Stripe retries
        log.exception("stripe_event_handler_failed event_id=%s err=%s", event_id, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "handler failed"
        ) from exc

    await mark_stripe_event_processed(
        session, event_id=event_id, event_type=event_type
    )
    return Response(status_code=status.HTTP_200_OK)


async def _dispatch(session: AsyncSession, event: dict) -> None:
    """Per-event-type side effects.

    Only the events we actually depend on are wired. Everything else is
    silently OK'd — Stripe will keep delivering them but they don't move
    our state.
    """
    et: str = event["type"]
    obj = event["data"]["object"]

    if et in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = obj.get("customer")
        if not customer_id:
            return
        sub_row = await get_subscription_by_stripe_customer(session, customer_id)
        if sub_row is None:
            log.warning(
                "stripe_subscription_event_no_match customer=%s", customer_id
            )
            return
        # First item's price gives us the plan.
        items = (obj.get("items") or {}).get("data") or []
        price_id = items[0]["price"]["id"] if items else None
        plan_key = _plan_from_price(price_id)
        await update_subscription_from_stripe(
            session,
            tenant_id=sub_row.tenant_id,
            stripe_subscription_id=obj.get("id"),
            plan=plan_key,
            status=obj.get("status"),
            current_period_end=_ts_to_dt(obj.get("current_period_end")),
        )

    elif et == "customer.subscription.deleted":
        customer_id = obj.get("customer")
        if not customer_id:
            return
        sub_row = await get_subscription_by_stripe_customer(session, customer_id)
        if sub_row is None:
            return
        await update_subscription_from_stripe(
            session,
            tenant_id=sub_row.tenant_id,
            status="canceled",
            plan="free",
        )

    elif et == "invoice.payment_succeeded":
        customer_id = obj.get("customer")
        if not customer_id:
            return
        sub_row = await get_subscription_by_stripe_customer(session, customer_id)
        if sub_row is None:
            return
        # Period rolled over — reset the rolling feedback counter.
        await reset_monthly_counters_if_due(session, sub_row.tenant_id)

    elif et == "invoice.payment_failed":
        customer_id = obj.get("customer")
        if not customer_id:
            return
        sub_row = await get_subscription_by_stripe_customer(session, customer_id)
        if sub_row is None:
            return
        await update_subscription_from_stripe(
            session, tenant_id=sub_row.tenant_id, status="past_due"
        )

    # else: silently no-op — Stripe sends many event types we don't track.


# Suppress unused-import warning on the few helpers re-exported indirectly.
_ = (Subscription, assert_quota, QuotaExceeded)
