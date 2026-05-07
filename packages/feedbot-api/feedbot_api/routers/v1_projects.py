"""JSON CRUD for projects, API keys, and chat links — consumed by the SPA.

Authorization layers (re-used from feedbot_api.deps):

- ``require_user``           — any logged-in user; can list visible projects.
- ``require_project_access`` — visible to project members + tenant admins.
- ``require_project_admin``  — only tenant admins; mutating ops on a project.
- ``require_tenant_admin``   — needed to create new projects in this tenant.

The 404-vs-403 boundary deliberately conflates "doesn't exist" and "you can't
see this" so members can't probe for project slugs they shouldn't know about.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from feedbot_core import audit
from feedbot_core.models import Project, User
from feedbot_core.repos import (
    create_project,
    delete_project,
    get_project_by_slug,
    issue_api_key,
    issue_chat_link_token,
    list_api_keys,
    list_chat_links,
    list_projects_for_user,
    revoke_api_key,
    stats_for_project,
    unlink_chat,
)
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import client_ip, client_user_agent
from feedbot_api.deps import (
    get_session,
    require_project_access,
    require_project_admin,
    require_tenant_admin,
    require_user,
)
from feedbot_api.schemas import (
    ApiKeyCreated,
    ApiKeyIn,
    ApiKeyOut,
    ChatLinkOut,
    ChatLinkTokenOut,
    ProjectIn,
    ProjectOut,
    ProjectSummary,
)

log = logging.getLogger("feedbot.v1.projects")

router = APIRouter(prefix="/v1", tags=["v1.projects"])


# ─── Projects ──────────────────────────────────────────────────────────────


@router.get(
    "/projects",
    response_model=list[ProjectSummary],
    summary="List projects visible to the current user",
)
async def list_projects(
    me: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectSummary]:
    """Owner/admin sees every project in the tenant; members see only their own."""
    rows = await list_projects_for_user(session, me)
    return [ProjectSummary(slug=p.slug, name=p.name, created_at=p.created_at) for p in rows]


@router.post(
    "/projects",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project (admin/owner only)",
    responses={status.HTTP_409_CONFLICT: {"description": "Slug already exists in this tenant."}},
)
async def create_project_(
    request: Request,
    body: ProjectIn,
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    existing = await get_project_by_slug(session, me.tenant_id, body.slug)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug already exists")
    project = await create_project(session, me.tenant_id, slug=body.slug, name=body.name)
    await audit.log_event(
        session,
        event="project.created",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"slug": project.slug, "name": project.name},
    )
    return ProjectOut(slug=project.slug, name=project.name, created_at=project.created_at)


@router.get(
    "/projects/{slug}",
    response_model=ProjectOut,
    summary="Get a project's detail (with feedback counts)",
)
async def get_project(
    slug: str,
    pair: tuple[User, Project] = Depends(require_project_access),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    _me, project = pair
    counts = await stats_for_project(session, project.id)
    return ProjectOut(
        slug=project.slug,
        name=project.name,
        created_at=project.created_at,
        feedback_count_by_status=counts,
    )


@router.delete(
    "/projects/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project and all its data (admin/owner only)",
)
async def delete_project_(
    slug: str,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    me, project = pair
    project_id = project.id
    project_slug = project.slug
    await delete_project(session, project)
    await audit.log_event(
        session,
        event="project.deleted",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"slug": project_slug},
    )


# ─── API keys ──────────────────────────────────────────────────────────────


def _to_key_out(k) -> ApiKeyOut:
    return ApiKeyOut(
        id=k.id,
        label=k.label,
        prefix=k.prefix,
        scope=k.scope,
        created_at=k.created_at,
        last_used_at=k.last_used_at,
        revoked_at=k.revoked_at,
    )


@router.get(
    "/projects/{slug}/api-keys",
    response_model=list[ApiKeyOut],
    summary="List API keys for a project (admin only)",
)
async def list_keys(
    slug: str,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyOut]:
    _me, project = pair
    rows = await list_api_keys(session, project.id)
    return [_to_key_out(k) for k in rows]


@router.post(
    "/projects/{slug}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new API key — secret is shown ONCE (admin only)",
)
async def create_key(
    slug: str,
    request: Request,
    body: ApiKeyIn,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreated:
    me, project = pair
    key, full = await issue_api_key(session, project.id, label=body.label, scope=body.scope)
    await audit.log_event(
        session,
        event="api_key.created",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"label": body.label, "scope": body.scope, "prefix": key.prefix},
    )
    out = _to_key_out(key)
    return ApiKeyCreated(**out.model_dump(), key=full)


@router.delete(
    "/projects/{slug}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key (admin only). Idempotent.",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Key not found in this project."}},
)
async def revoke_key(
    slug: str,
    key_id: int,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    me, project = pair
    revoked = await revoke_api_key(session, project.id, key_id)
    if not revoked:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "key not found")
    await audit.log_event(
        session,
        event="api_key.revoked",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"key_id": key_id},
    )


# ─── Chat links ────────────────────────────────────────────────────────────


@router.get(
    "/projects/{slug}/chat-links",
    response_model=list[ChatLinkOut],
    summary="List chat links for a project",
)
async def get_chat_links(
    slug: str,
    pair: tuple[User, Project] = Depends(require_project_access),
    session: AsyncSession = Depends(get_session),
) -> list[ChatLinkOut]:
    _me, project = pair
    rows = await list_chat_links(session, project.id)
    return [
        ChatLinkOut(
            id=row.id,
            platform=row.platform,
            chat_id=row.chat_id,
            title=row.title,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post(
    "/projects/{slug}/chat-link-tokens",
    response_model=ChatLinkTokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a 15-min deep-link token to bind a Telegram chat to this project (admin only)",
)
async def create_chat_link_token(
    slug: str,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> ChatLinkTokenOut:
    me, project = pair
    token = await issue_chat_link_token(session, project.id, created_by_email=me.email)
    bot_user = os.getenv("FEEDBOT_TELEGRAM_BOT_USERNAME", "")
    deep_link = f"https://t.me/{bot_user}?startgroup=link_{token.token}" if bot_user else ""
    await audit.log_event(
        session,
        event="chat_link_token.issued",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"has_bot_username": bool(bot_user)},
    )
    return ChatLinkTokenOut(
        token=token.token,
        deep_link=deep_link,
        expires_at=token.expires_at,
    )


@router.delete(
    "/projects/{slug}/chat-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect a chat from this project (admin only)",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Chat link not found in this project."}},
)
async def delete_chat_link(
    slug: str,
    link_id: int,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    me, project = pair
    removed = await unlink_chat(session, project.id, link_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chat link not found")
    await audit.log_event(
        session,
        event="chat_link.removed",
        tenant_id=me.tenant_id,
        user_id=me.id,
        project_id=project.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"chat_link_id": link_id},
    )
