"""Tenant team management — invite, list members, change roles."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from feedbot_core.models import Role, User
from feedbot_core.repos import (
    delete_user,
    get_user_by_email,
    issue_invite,
    list_pending_invites,
    list_tenant_users,
    revoke_invite,
    update_user_role,
)
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import (
    get_session,
    require_owner,
    require_tenant_admin,
)
from feedbot_api.email_backend import email_backend_from_env
from feedbot_api.templating import render

router = APIRouter(prefix="/app/team", tags=["team"])


@router.get("", response_class=HTMLResponse)
async def team_home(
    request: Request,
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    members = await list_tenant_users(session, me.tenant_id)
    invites = await list_pending_invites(session, me.tenant_id)
    base = str(request.base_url).rstrip("/")
    return render(
        request,
        "team.html",
        {
            "me": me,
            "members": members,
            "invites": invites,
            "invite_base_url": f"{base}/invites/",
        },
    )


@router.post("/invites")
async def invite_create(
    request: Request,
    email: str = Form(...),
    role: str = Form("member"),
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    email = email.lower().strip()
    try:
        chosen = Role(role)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid role") from exc
    if chosen == Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner cannot be transferred via invite")

    existing = await get_user_by_email(session, email)
    if existing and existing.tenant_id == me.tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user already in this tenant")

    invite = await issue_invite(
        session,
        tenant_id=me.tenant_id,
        email=email,
        role=chosen,
        invited_by_user_id=me.id,
    )

    base = str(request.base_url).rstrip("/")
    link = f"{base}/invites/{invite.token}"
    # Delivery is best-effort here; the invite row is durable and shown in the
    # dashboard so the admin can copy/resend if email fails.
    with contextlib.suppress(Exception):
        email_backend_from_env().send(
            to=email,
            subject=f"You've been invited to {me.tenant.name if me.tenant else 'Feedbot'}",
            body=f"Accept your invite:\n\n{link}\n\nExpires in 7 days.",
        )

    return RedirectResponse("/app/team", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/invites/{invite_id}/revoke")
async def invite_revoke(
    invite_id: int,
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    from feedbot_core.models import Invite

    invite = await session.get(Invite, invite_id)
    if invite and invite.tenant_id == me.tenant_id and invite.used_at is None:
        await revoke_invite(session, invite)
    return RedirectResponse("/app/team", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/role")
async def user_set_role(
    user_id: int,
    role: str = Form(...),
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    target = await session.get(User, user_id)
    if not target or target.tenant_id != me.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if target.role == Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot modify the owner")
    try:
        chosen = Role(role)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid role") from exc
    if chosen == Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ownership cannot be granted via this endpoint")
    await update_user_role(session, target, chosen)
    return RedirectResponse("/app/team", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/delete")
async def user_delete(
    user_id: int,
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    target = await session.get(User, user_id)
    if not target or target.tenant_id != me.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if target.role == Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot delete the owner")
    if target.id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "use logout to remove yourself")
    await delete_user(session, target)
    return RedirectResponse("/app/team", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/transfer-ownership")
async def transfer_ownership(
    new_owner_id: int = Form(...),
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Owner-only: hand the crown to another admin in the same tenant."""
    target = await session.get(User, new_owner_id)
    if not target or target.tenant_id != me.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if target.id == me.id:
        return RedirectResponse("/app/team", status_code=status.HTTP_303_SEE_OTHER)
    await update_user_role(session, me, Role.ADMIN)
    await update_user_role(session, target, Role.OWNER)
    return RedirectResponse("/app/team", status_code=status.HTTP_303_SEE_OTHER)
