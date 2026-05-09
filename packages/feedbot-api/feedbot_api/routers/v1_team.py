"""JSON team / invites / members endpoints.

Authorization layers (re-used from feedbot_api.deps):

- ``require_tenant_admin`` — invite, list members, change roles.
- ``require_owner``        — transfer ownership.
- ``require_project_admin``— add/remove project members.
- (none, public)           — invite preview + accept (token-gated).

Security boundaries enforced here:

- The ``owner`` role is **never** assignable via invite or PATCH; the only
  path to owner is ``/setup`` (bootstrap) or ``transfer-ownership`` (which
  demotes the previous owner to admin in the same transaction).
- Cross-tenant probes return 404 (not 403) — same convention as F2.4.
- Invite preview never reveals whether the email exists in another tenant.
- Invite tokens are 32 bytes urlsafe, single-use, 7-day TTL (issued by
  ``feedbot_core.repos.issue_invite``); revoked invites are deleted, not
  soft-flagged, since the audit log captures the full history.
"""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from feedbot_core import audit, auth_sessions
from feedbot_core.billing import QuotaExceeded, assert_quota
from feedbot_core.models import Invite, Project, Role, Tenant, User
from feedbot_core.repos import (
    add_project_member,
    delete_user,
    get_project_by_slug,
    get_user_by_email,
    issue_invite,
    list_pending_invites,
    list_project_members,
    list_tenant_users,
    redeem_invite,
    remove_project_member,
    revoke_invite,
    update_user_role,
)
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.billing import http_402_from
from feedbot_api.cookies import (
    client_ip,
    client_user_agent,
    set_session_cookie,
)
from feedbot_api.deps import (
    get_session,
    require_owner,
    require_project_admin,
    require_tenant_admin,
)
from feedbot_api.email_backend import resolve_email_backend
from feedbot_api.schemas import (
    InviteAcceptIn,
    InviteIn,
    InviteOut,
    InvitePreviewOut,
    ProjectMemberAddIn,
    TenantUserOut,
    TenantUserPatchIn,
)

log = logging.getLogger("feedbot.v1.team")

router = APIRouter(prefix="/v1", tags=["v1.team"])


# ─── Tenant users (team) ───────────────────────────────────────────────────


def _to_user_out(u: User) -> TenantUserOut:
    return TenantUserOut(id=u.id, email=u.email, role=str(u.role), created_at=u.created_at)


@router.get(
    "/tenant/users",
    response_model=list[TenantUserOut],
    summary="List every user in the tenant (admin/owner only)",
)
async def list_tenant_users_(
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> list[TenantUserOut]:
    rows = await list_tenant_users(session, me.tenant_id)
    return [_to_user_out(u) for u in rows]


@router.patch(
    "/tenant/users/{user_id}",
    response_model=TenantUserOut,
    summary="Change a user's role within the tenant (admin/owner only)",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "Cannot modify the owner; cannot grant the owner role here."
        },
        status.HTTP_404_NOT_FOUND: {"description": "User not in this tenant."},
    },
)
async def patch_tenant_user(
    user_id: int,
    request: Request,
    body: TenantUserPatchIn,
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> TenantUserOut:
    target = await session.get(User, user_id)
    if not target or target.tenant_id != me.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if target.role == Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot modify the owner")

    new_role = Role(body.role)  # schema already constrained to admin|member
    if new_role == Role.OWNER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "ownership cannot be granted via this endpoint — use transfer-ownership",
        )
    old_role = str(target.role)
    await update_user_role(session, target, new_role)
    await audit.log_event(
        session,
        event="user.role_changed",
        tenant_id=me.tenant_id,
        user_id=me.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"target_user_id": target.id, "from": old_role, "to": str(new_role)},
    )
    return _to_user_out(target)


@router.delete(
    "/tenant/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a user from the tenant (admin/owner only)",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Use logout to remove yourself."},
        status.HTTP_403_FORBIDDEN: {"description": "Cannot delete the owner."},
        status.HTTP_404_NOT_FOUND: {"description": "User not in this tenant."},
    },
)
async def delete_tenant_user(
    user_id: int,
    request: Request,
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    target = await session.get(User, user_id)
    if not target or target.tenant_id != me.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if target.role == Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot delete the owner")
    if target.id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "use logout to remove yourself")

    target_email = target.email
    target_id = target.id
    # Revoke any active sessions for this user atomically with the delete.
    await auth_sessions.revoke_all_for_user(session, target.id)
    await delete_user(session, target)
    await audit.log_event(
        session,
        event="user.deleted",
        tenant_id=me.tenant_id,
        user_id=me.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"target_user_id": target_id, "target_email": target_email},
    )


@router.post(
    "/tenant/transfer-ownership",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Owner-only: hand the role to another admin in the same tenant",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Target user not in this tenant."},
        status.HTTP_400_BAD_REQUEST: {"description": "Cannot transfer to yourself."},
    },
)
async def transfer_ownership(
    request: Request,
    body: ProjectMemberAddIn,  # re-uses {user_id}
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> None:
    target = await session.get(User, body.user_id)
    if not target or target.tenant_id != me.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if target.id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot transfer to yourself")

    await update_user_role(session, me, Role.ADMIN)
    await update_user_role(session, target, Role.OWNER)
    await audit.log_event(
        session,
        event="ownership.transferred",
        tenant_id=me.tenant_id,
        user_id=me.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"new_owner_user_id": target.id, "new_owner_email": target.email},
    )


# ─── Invites ───────────────────────────────────────────────────────────────


def _to_invite_out(invite: Invite, project_slug: str | None, inviter_email: str | None) -> InviteOut:
    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=str(invite.role),
        project_slug=project_slug,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        used_at=invite.used_at,
        invited_by_email=inviter_email,
    )


@router.get(
    "/invites",
    response_model=list[InviteOut],
    summary="List pending invites for this tenant (admin/owner only)",
)
async def list_invites(
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> list[InviteOut]:
    invites = await list_pending_invites(session, me.tenant_id)
    out: list[InviteOut] = []
    for inv in invites:
        slug: str | None = None
        if inv.project_id is not None:
            project = await session.get(Project, inv.project_id)
            slug = project.slug if project else None
        inviter = await session.get(User, inv.invited_by_user_id)
        out.append(_to_invite_out(inv, slug, inviter.email if inviter else None))
    return out


@router.post(
    "/invites",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an invite + send the email (admin/owner only)",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "User already in this tenant; or invalid role; or unknown project_slug."
        },
        status.HTTP_403_FORBIDDEN: {"description": "Owner role cannot be invited."},
    },
)
async def create_invite(
    request: Request,
    body: InviteIn,
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> InviteOut:
    email = body.email.lower().strip()
    role = Role(body.role)  # schema constrains to admin|member
    if role == Role.OWNER:  # defensive — schema should prevent it
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner cannot be invited")

    existing = await get_user_by_email(session, email)
    if existing and existing.tenant_id == me.tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user already in this tenant")

    # Member quota counts active users + pending invites — sending the invite
    # already reserves the seat. No-op on self-host (billing disabled).
    try:
        await assert_quota(session, me.tenant_id, "member")
    except QuotaExceeded as exc:
        raise http_402_from(exc) from exc

    project_id: int | None = None
    if body.project_slug:
        project = await get_project_by_slug(session, me.tenant_id, body.project_slug)
        if project is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown project_slug")
        project_id = project.id

    invite = await issue_invite(
        session,
        tenant_id=me.tenant_id,
        email=email,
        role=role,
        invited_by_user_id=me.id,
        project_id=project_id,
    )

    # Public SPA route (apps/web/src/routes/(auth)/invites.$token.tsx).
    # NOT the API path: in the cloud edge nginx strips /api before reaching
    # the API container, and self-host Caddy routes /v1/* straight to the
    # SPA — both setups need the SPA-side path here, not /v1/invites/preview.
    base = str(request.base_url).rstrip("/")
    link = f"{base}/invites/{invite.token}"
    # Best-effort delivery; the invite row is durable.
    tenant = await session.get(Tenant, me.tenant_id)
    workspace_name = tenant.name if tenant else "Feedbot"
    backend = await resolve_email_backend(session)
    with contextlib.suppress(Exception):
        backend.send(
            to=email,
            subject=f"You've been invited to {workspace_name}",
            body=f"Accept your invite:\n\n{link}\n\nExpires in 7 days.\n",
        )

    await audit.log_event(
        session,
        event="invite.created",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"invite_id": invite.id, "email": email, "role": str(role)},
    )

    return _to_invite_out(invite, body.project_slug, me.email)


@router.delete(
    "/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a pending invite (admin/owner only)",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Invite not in this tenant or already used."}},
)
async def delete_invite(
    invite_id: int,
    request: Request,
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    invite = await session.get(Invite, invite_id)
    if not invite or invite.tenant_id != me.tenant_id or invite.used_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invite not found")

    invite_email = invite.email
    project_id = invite.project_id
    await revoke_invite(session, invite)
    await audit.log_event(
        session,
        event="invite.revoked",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"invite_id": invite_id, "email": invite_email},
    )


# ─── Public invite preview + accept (no auth) ─────────────────────────────


@router.get(
    "/invites/preview",
    response_model=InvitePreviewOut,
    summary="Preview an invite (no auth) — used by the SPA's accept page",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Invalid or expired token."}},
)
async def preview_invite(
    token: str = Query(min_length=8, max_length=128),
    session: AsyncSession = Depends(get_session),
) -> InvitePreviewOut:
    """Open endpoint: anyone with the token can read the invite metadata. We
    deliberately surface only what's needed to render the accept screen
    (workspace name, email, role, project name, expiry) — never the inviter's
    email or anything that would help enumerate the tenant."""
    from feedbot_core.models import Invite
    from sqlalchemy import select

    rows = await session.execute(select(Invite).where(Invite.token == token))
    invite = rows.scalar_one_or_none()
    if not invite or invite.used_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invalid or expired invite")
    from datetime import UTC, datetime

    if invite.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invalid or expired invite")

    tenant = await session.get(Tenant, invite.tenant_id)
    project_name: str | None = None
    if invite.project_id is not None:
        project = await session.get(Project, invite.project_id)
        project_name = project.name if project else None

    return InvitePreviewOut(
        email=invite.email,
        role=str(invite.role),
        tenant_name=tenant.name if tenant else "",
        project_name=project_name,
        expires_at=invite.expires_at,
    )


@router.post(
    "/invites/accept",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Accept an invite (no auth) — creates the user and starts a session",
    responses={status.HTTP_400_BAD_REQUEST: {"description": "Invalid or expired token."}},
)
async def accept_invite(
    request: Request,
    body: InviteAcceptIn,
    session: AsyncSession = Depends(get_session),
):
    user = await redeem_invite(session, body.token)
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired invite")

    db_session = await auth_sessions.create(
        session,
        user=user,
        user_agent=client_user_agent(request),
        ip=client_ip(request),
    )
    await audit.log_event(
        session,
        event="invite.accepted",
        tenant_id=user.tenant_id,
        user_id=user.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"session_id_prefix": db_session.id[:8], "channel": "spa"},
    )

    from fastapi.responses import Response

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(response, db_session.id)
    return response


# ─── Project members ──────────────────────────────────────────────────────


@router.get(
    "/projects/{slug}/members",
    response_model=list[TenantUserOut],
    summary="List members of a project (admin only)",
)
async def list_members(
    slug: str,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> list[TenantUserOut]:
    _me, project = pair
    rows = await list_project_members(session, project.id)
    return [_to_user_out(u) for u in rows]


@router.post(
    "/projects/{slug}/members",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Add an existing tenant user to this project (admin only)",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "User not in this tenant."},
        status.HTTP_409_CONFLICT: {"description": "User is already a member."},
    },
)
async def add_member(
    slug: str,
    request: Request,
    body: ProjectMemberAddIn,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    me, project = pair
    target = await session.get(User, body.user_id)
    if not target or target.tenant_id != me.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    added = await add_project_member(session, project.id, target.id)
    if not added:
        raise HTTPException(status.HTTP_409_CONFLICT, "already a member")

    await audit.log_event(
        session,
        event="project_member.added",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"target_user_id": target.id, "target_email": target.email},
    )


@router.delete(
    "/projects/{slug}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from this project (admin only)",
    responses={status.HTTP_404_NOT_FOUND: {"description": "User is not a member of this project."}},
)
async def remove_member(
    slug: str,
    user_id: int,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    me, project = pair
    removed = await remove_project_member(session, project.id, user_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not a member")

    await audit.log_event(
        session,
        event="project_member.removed",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"target_user_id": user_id},
    )
