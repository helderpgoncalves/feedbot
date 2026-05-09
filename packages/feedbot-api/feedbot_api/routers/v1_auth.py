"""JSON auth + identity endpoints for the SPA.

These mirror the cookie-based form flow in ``routers/auth.py`` but speak
JSON, so the React SPA in ``apps/web`` can drive login without HTML
templates. Cookies are issued the same way (``fb_session`` + ``mlnonce``)
so a browser that authenticated via the form is also authenticated for
``/v1/me``, and vice-versa.

Tag is ``v1.auth`` so the OpenAPI groups them sensibly.
"""

from __future__ import annotations

import contextlib
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from feedbot_core import audit, auth_sessions
from feedbot_core.models import Tenant, User
from feedbot_core.billing import is_billing_enabled
from feedbot_core.billing.settings import stripe_trial_days
from feedbot_core.repos import (
    TenantAlreadyExists,
    bootstrap_owner,
    consume_magic_link,
    count_users,
    create_tenant_with_owner,
    ensure_subscription,
    get_user_by_email,
    issue_magic_link,
    list_projects_for_user,
)
from feedbot_core.settings import is_signup_enabled
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import (
    NONCE_BYTES,
    NONCE_COOKIE,
    SESSION_COOKIE,
    clear_nonce_cookie,
    clear_session_cookie,
    client_ip,
    client_user_agent,
    hash_nonce,
    set_nonce_cookie,
    set_session_cookie,
)
from feedbot_api.deps import get_session, require_user
from feedbot_api.email_backend import (
    is_email_delivery_safe,
    resolve_email_backend,
)
from feedbot_api.rate_limit import limiter
from feedbot_api.schemas import (
    LoginIn,
    LoginOut,
    MeOut,
    ProjectSummary,
    SessionOut,
    SetupIn,
    SetupOut,
    SetupStatusOut,
    SignupIn,
    SignupOut,
)

log = logging.getLogger("feedbot.v1.auth")

router = APIRouter(prefix="/v1", tags=["v1.auth"])


# ─── Login: email → magic link ─────────────────────────────────────────────


@router.post(
    "/auth/login",
    response_model=LoginOut,
    summary="Request a magic-link sign-in email",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Email delivery is not configured on this deployment."
        }
    },
)
@limiter.limit("5/15minutes")
async def login(
    request: Request,
    body: LoginIn,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Send a magic-link to ``body.email``.

    Always responds 200 with ``{"sent": true}`` — whether the email is
    registered or not is intentionally hidden to prevent enumeration.

    On every call (registered or not) the response sets an ``mlnonce``
    cookie. The link the user clicks must be opened in the same browser
    or the magic-link verifier will mark the login as ``cross_device``
    and email a notice.
    """
    if not await is_email_delivery_safe(session):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "email delivery not configured",
        )

    email = body.email.lower().strip()
    user = await get_user_by_email(session, email)

    nonce_raw = secrets.token_urlsafe(NONCE_BYTES)
    nonce_hash = hash_nonce(nonce_raw)

    if user is not None:
        token_raw = secrets.token_urlsafe(24)
        await issue_magic_link(session, email, token_raw, nonce_hash=nonce_hash)
        base = str(request.base_url).rstrip("/")
        # Point at the SPA's `/magic` route — it calls GET /v1/auth/magic via
        # fetch and renders progress / error UI, instead of dropping the user
        # onto a blank 204.
        link = f"{base}/magic?email={email}&token={token_raw}"
        backend = await resolve_email_backend(session)
        with contextlib.suppress(Exception):
            backend.send(
                to=email,
                subject="Your Feedbot sign-in link",
                body=(
                    f"Sign in to Feedbot:\n\n{link}\n\n"
                    "This link expires in 15 minutes and can be used once.\n"
                ),
            )

    response = JSONResponse(LoginOut(sent=True).model_dump())
    set_nonce_cookie(response, nonce_raw)
    return response


# ─── Signup: multi-tenant cloud self-serve ─────────────────────────────────


@router.post(
    "/signup",
    response_model=SignupOut,
    summary="Create a new tenant + owner and email a magic-link",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Signup is disabled on this deployment."
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Email delivery is not configured on this deployment."
        },
    },
)
@limiter.limit("3/hour")
async def signup(
    request: Request,
    body: SignupIn,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Create a brand-new tenant + owner and send a magic-link to ``body.email``.

    Behaviour matrix:

    - ``FEEDBOT_ALLOW_SIGNUP`` unset/false → 404 (route appears not to
      exist). Self-host stays invite-only by default.
    - SMTP not configured (console backend in production) → 503, same as
      the regular login flow. Without email delivery, the magic-link
      can't reach the user.
    - Email already owns/belongs to a tenant → response is identical to
      the new-tenant path (``{sent: true}``) so an attacker can't probe
      which addresses are registered.

    On success, the response body is identical to the regular login —
    the SPA shows the same "check your email" card.
    """
    if not is_signup_enabled():
        # Hide the route entirely when disabled. Returning 403 would leak
        # that this endpoint exists; 404 mirrors what an unrouted path does.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    if not await is_email_delivery_safe(session):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "email delivery not configured",
        )

    email = body.email.lower().strip()
    tenant_name = body.tenant_name.strip()
    nonce_raw = secrets.token_urlsafe(NONCE_BYTES)
    nonce_hash = hash_nonce(nonce_raw)

    # The signup audit fires before the create attempt so we capture
    # repeat attempts even when they're swallowed by the dedupe path.
    await audit.log_event(
        session,
        event="signup.attempt",
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"email": email, "channel": "spa"},
    )

    try:
        user = await create_tenant_with_owner(
            session, email=email, tenant_name=tenant_name
        )
    except TenantAlreadyExists:
        # Generic success — emit a magic-link to the *existing* user so
        # the legitimate owner can sign in even if they hit /signup by
        # mistake. This is identical UX to a duplicate /login submit.
        existing_user = await get_user_by_email(session, email)
        if existing_user is not None:
            token_raw = secrets.token_urlsafe(24)
            await issue_magic_link(
                session, existing_user.email, token_raw, nonce_hash=nonce_hash
            )
            base = str(request.base_url).rstrip("/")
            link = f"{base}/magic?email={existing_user.email}&token={token_raw}"
            backend = await resolve_email_backend(session)
            with contextlib.suppress(Exception):
                backend.send(
                    to=existing_user.email,
                    subject="Your Feedbot sign-in link",
                    body=(
                        f"Sign in to Feedbot:\n\n{link}\n\n"
                        "This link expires in 15 minutes and can be used once.\n"
                    ),
                )
        response = JSONResponse(SignupOut(sent=True).model_dump())
        set_nonce_cookie(response, nonce_raw)
        return response

    # Fresh tenant — audit and email a welcome magic link.
    await audit.log_event(
        session,
        event="tenant.created",
        tenant_id=user.tenant_id,
        user_id=user.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"email": user.email, "channel": "spa"},
    )

    # Cloud commercial: provision Stripe customer + free-plan Subscription
    # row immediately so the dashboard can offer a "Start free trial" CTA
    # on first sign-in. Failures here are best-effort: a missing Stripe
    # customer can be backfilled by the first /billing/checkout call.
    if is_billing_enabled():
        from feedbot_core.billing.stripe_client import (
            StripeError,
            create_customer,
        )

        sub = await ensure_subscription(
            session, user.tenant_id, plan="free", status="active"
        )
        if not sub.stripe_customer_id:
            try:
                customer = await create_customer(
                    email=user.email,
                    tenant_id=user.tenant_id,
                    name=body.tenant_name.strip() or None,
                    idempotency_key=f"customer-{user.tenant_id}",
                )
                sub.stripe_customer_id = customer.id
                await session.flush()
            except StripeError:
                log.warning(
                    "stripe_customer_create_failed_during_signup tenant=%s",
                    user.tenant_id,
                )

        # Trial-days surfaced via env so we can run a 7-day push without
        # redeploying. Reserved for use by the SPA's "you have N days
        # left" banner; the actual trial subscription is created when
        # the user clicks "Upgrade" and goes through Checkout.
        _ = stripe_trial_days()

    token_raw = secrets.token_urlsafe(24)
    await issue_magic_link(session, user.email, token_raw, nonce_hash=nonce_hash)
    base = str(request.base_url).rstrip("/")
    link = f"{base}/magic?email={user.email}&token={token_raw}"
    backend = await resolve_email_backend(session)
    with contextlib.suppress(Exception):
        backend.send(
            to=user.email,
            subject="Welcome to Feedbot — sign in",
            body=(
                f"Your Feedbot workspace is ready.\n\n"
                f"Sign in:\n\n{link}\n\n"
                "This link expires in 15 minutes and can be used once.\n"
            ),
        )

    response = JSONResponse(SignupOut(sent=True).model_dump())
    set_nonce_cookie(response, nonce_raw)
    return response


# ─── Magic-link verification ───────────────────────────────────────────────


@router.get(
    "/auth/magic",
    summary="Consume a magic-link token and start a session",
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Session created; cookie set."},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid or expired link."},
    },
)
@limiter.limit("10/15minutes")
async def magic(
    request: Request,
    email: str,
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Consume a magic-link and issue a server-side session cookie.

    On success, sets the ``fb_session`` cookie and clears ``mlnonce``.
    The SPA should treat any 2xx response as "logged in" and refetch
    ``/v1/me`` to load identity.
    """
    email = email.lower().strip()
    user = await get_user_by_email(session, email)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired link")

    ok, bound_nonce_hash = await consume_magic_link(session, email, token)
    if not ok:
        await audit.log_event(
            session,
            event="login.fail",
            tenant_id=user.tenant_id,
            user_id=user.id,
            ip=client_ip(request),
            user_agent=client_user_agent(request),
            details={"reason": "invalid_or_expired_link", "channel": "spa"},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired link")

    cookie_nonce = request.cookies.get(NONCE_COOKIE)
    cross_device = (
        bound_nonce_hash is not None
        and (not cookie_nonce or hash_nonce(cookie_nonce) != bound_nonce_hash)
    )

    db_session = await auth_sessions.create(
        session,
        user=user,
        user_agent=client_user_agent(request),
        ip=client_ip(request),
    )
    await audit.log_event(
        session,
        event=("login.cross_device" if cross_device else "login.ok"),
        tenant_id=user.tenant_id,
        user_id=user.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"session_id_prefix": db_session.id[:8], "channel": "spa"},
    )

    if cross_device:
        backend = await resolve_email_backend(session)
        with contextlib.suppress(Exception):
            backend.send(
                to=email,
                subject="New Feedbot sign-in",
                body=(
                    "A new sign-in to your Feedbot account just happened from a "
                    "different browser than the one that requested the magic link.\n\n"
                    f"  IP:         {client_ip(request) or 'unknown'}\n"
                    f"  User-agent: {client_user_agent(request) or 'unknown'}\n\n"
                    "If this was you, no action is needed.\n"
                    "If not, sign in again and revoke all sessions from /security.\n"
                ),
            )

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(response, db_session.id)
    clear_nonce_cookie(response)
    return response


# ─── Logout ────────────────────────────────────────────────────────────────


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current session",
)
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke just the session that authenticated this request and clear the cookie.

    Idempotent — returns 204 even if no cookie was sent.
    """
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        revoked = await auth_sessions.revoke(session, sid)
        if revoked:
            await audit.log_event(
                session,
                event="session.revoked",
                ip=client_ip(request),
                user_agent=client_user_agent(request),
                details={"reason": "user_logout", "session_id_prefix": sid[:8], "channel": "spa"},
            )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.post(
    "/auth/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke every session of the current user",
)
async def logout_all(
    request: Request,
    me: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke every active session of ``me`` (including the one making the request).

    Useful for "Sign out everywhere" on the future Security page.
    """
    revoked = await auth_sessions.revoke_all_for_user(session, me.id)
    await audit.log_event(
        session,
        event="session.revoked.bulk",
        tenant_id=me.tenant_id,
        user_id=me.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"count": revoked, "channel": "spa"},
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


# ─── Active session listing (for the future Security page) ─────────────────


@router.get(
    "/auth/sessions",
    response_model=list[SessionOut],
    summary="List active sessions for the current user",
)
async def list_sessions(
    request: Request,
    me: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[SessionOut]:
    rows = await auth_sessions.list_active(session, me.id)
    current_sid = request.cookies.get(SESSION_COOKIE) or ""
    return [
        SessionOut(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            user_agent=row.user_agent,
            ip=row.ip,
            is_current=(row.id == current_sid),
        )
        for row in rows
    ]


# ─── Identity ──────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=MeOut,
    summary="Identity + visible projects for the current user",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No active session."},
    },
)
async def me(
    me: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    """Everything the SPA needs at boot: identity, role, tenant, projects.

    A 401 here tells the SPA to redirect the user to the login screen.
    """
    projects = await list_projects_for_user(session, me)
    is_setup_complete = (await count_users(session)) > 0
    # Fetch tenant explicitly — the lazy `me.tenant` relationship would trigger
    # an implicit SELECT outside the async greenlet on serialization.
    tenant = await session.get(Tenant, me.tenant_id)
    return MeOut(
        user={
            "id": me.id,
            "email": me.email,
            "role": str(me.role),
            "tenant_id": me.tenant_id,
        },
        tenant={
            "id": me.tenant_id,
            "name": tenant.name if tenant else "",
        },
        projects=[
            ProjectSummary(
                slug=p.slug,
                name=p.name,
                created_at=p.created_at,
            )
            for p in projects
        ],
        is_setup_complete=is_setup_complete,
    )


# ─── First-run bootstrap ───────────────────────────────────────────────────


@router.get(
    "/setup-status",
    response_model=SetupStatusOut,
    summary="Whether the deployment still needs first-run bootstrap",
)
async def setup_status(session: AsyncSession = Depends(get_session)) -> SetupStatusOut:
    """Cheap check the SPA does at boot to decide whether to route the user
    to ``/setup`` or to ``/login``.

    No auth — there's no user yet when this matters, and post-bootstrap the
    answer is a stable ``False``.
    """
    return SetupStatusOut(required=(await count_users(session)) == 0)


@router.post(
    "/setup",
    response_model=SetupOut,
    summary="Bootstrap the first owner — only valid while the users table is empty",
    responses={
        status.HTTP_410_GONE: {"description": "Setup already complete."},
    },
)
@limiter.limit("3/15minutes")
async def setup_bootstrap(
    request: Request,
    body: SetupIn,
    session: AsyncSession = Depends(get_session),
) -> SetupOut:
    """Create the first tenant + owner user, then email them a magic link.

    On deployments without working SMTP we fall back to returning the link
    inline — the SPA renders it as a one-time button so the new owner can
    finish onboarding without having to dig through container logs.
    """
    if (await count_users(session)) > 0:
        raise HTTPException(status.HTTP_410_GONE, "setup already complete")

    email = body.email.lower().strip()
    tenant_name = body.tenant_name.strip()
    user = await bootstrap_owner(session, email=email, tenant_name=tenant_name)

    raw = secrets.token_urlsafe(24)
    await issue_magic_link(session, user.email, raw)
    base = str(request.base_url).rstrip("/")
    link = f"{base}/magic?email={user.email}&token={raw}"

    delivered = False
    if await is_email_delivery_safe(session):
        backend = await resolve_email_backend(session)
        with contextlib.suppress(Exception):
            backend.send(
                to=user.email,
                subject="Welcome to Feedbot — sign in",
                body=(
                    "You're the owner of this Feedbot instance.\n\n"
                    f"Sign in:\n\n{link}\n\n"
                    "This link expires in 15 minutes and can be used once.\n"
                ),
            )
            delivered = True

    return SetupOut(
        email=user.email,
        delivered=delivered,
        fallback_link=None if delivered else link,
    )
