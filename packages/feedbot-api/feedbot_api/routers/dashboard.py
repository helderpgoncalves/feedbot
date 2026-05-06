"""Dashboard pages — projects list, single-project view, key/chat-link management.

Authorization layers:
    require_user            — any logged-in user
    require_project_access  — visible to project members + tenant admins
    require_project_admin   — only tenant admins (mutating ops on a project)
    require_tenant_admin    — needed to create new projects in this tenant
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from feedbot_core.models import ApiKey, Project, User
from feedbot_core.repos import (
    create_project,
    issue_api_key,
    issue_chat_link_token,
    list_chat_links,
    list_feedbacks,
    list_project_members,
    list_projects_for_user,
    list_tenant_users,
    stats_for_project,
    unlink_chat,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import (
    get_session,
    require_project_access,
    require_project_admin,
    require_tenant_admin,
    require_user,
)
from feedbot_api.templating import render

router = APIRouter(prefix="/app", tags=["dashboard"])


@router.get("", response_class=HTMLResponse)
async def home(
    request: Request,
    me: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    projects = await list_projects_for_user(session, me)
    return render(request, "dashboard.html", {"me": me, "projects": projects})


@router.post("/projects")
async def create_project_(
    slug: str = Form(...),
    name: str = Form(...),
    me: User = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    slug = slug.strip().lower()
    name = name.strip()
    if not slug or not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "slug and name required")
    await create_project(session, me.tenant_id, slug=slug, name=name)
    return RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/projects/{slug}", response_class=HTMLResponse)
async def project_view(
    slug: str,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_access),
    session: AsyncSession = Depends(get_session),
) -> Response:
    me, project = pair

    feedbacks = await list_feedbacks(session, project.id, limit=100)
    keys = (await session.execute(select(ApiKey).where(ApiKey.project_id == project.id))).scalars().all()
    chats = await list_chat_links(session, project.id)
    members = await list_project_members(session, project.id)
    stats = await stats_for_project(session, project.id)

    addable_users: list[User] = []
    if me.is_admin:
        all_users = await list_tenant_users(session, me.tenant_id)
        member_ids = {m.id for m in members}
        addable_users = [u for u in all_users if u.id not in member_ids]

    flash_key = request.session.pop("new_key", None)
    flash_link = request.session.pop("new_chat_link", None)

    return render(
        request,
        "project.html",
        {
            "me": me,
            "project": project,
            "feedbacks": feedbacks,
            "keys": keys,
            "chats": chats,
            "members": members,
            "addable_users": addable_users,
            "stats": stats,
            "new_key": flash_key,
            "new_chat_link": flash_link,
            "telegram_bot_username": os.getenv("FEEDBOT_TELEGRAM_BOT_USERNAME", ""),
        },
    )


@router.post("/projects/{slug}/keys")
async def create_key_(
    slug: str,
    request: Request,
    label: str = Form(...),
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    _me, project = pair
    _, full = await issue_api_key(session, project.id, label=label.strip() or "unlabelled")
    request.session["new_key"] = full
    return RedirectResponse(f"/app/projects/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{slug}/chat-links")
async def create_chat_link_(
    slug: str,
    request: Request,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    me, project = pair
    token = await issue_chat_link_token(session, project.id, created_by_email=me.email)
    bot_user = os.getenv("FEEDBOT_TELEGRAM_BOT_USERNAME", "")
    deep_link = f"https://t.me/{bot_user}?startgroup=link_{token.token}" if bot_user else ""
    request.session["new_chat_link"] = {
        "token": token.token,
        "deep_link": deep_link,
        "expires_at": token.expires_at.isoformat(),
    }
    return RedirectResponse(f"/app/projects/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/projects/{slug}/chat-links/{link_id}/delete")
async def delete_chat_link_(
    slug: str,
    link_id: int,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    _me, project = pair
    await unlink_chat(session, project.id, link_id)
    return RedirectResponse(f"/app/projects/{slug}", status_code=status.HTTP_303_SEE_OTHER)
