import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from feedbot_core.models import ApiKey, Project, User
from feedbot_core.repos import (
    create_project,
    issue_api_key,
    issue_chat_link_token,
    list_chat_links,
    list_feedbacks,
    list_projects,
    stats_for_project,
    unlink_chat,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session, require_session_user
from feedbot_api.templating import templates

router = APIRouter(prefix="/app", tags=["dashboard"])


async def _user(session: AsyncSession, email: str) -> User:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        raise HTTPException(401, "unknown user")
    return user


@router.get("", response_class=HTMLResponse)
async def home(
    request: Request,
    email: str = Depends(require_session_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _user(session, email)
    projects = await list_projects(session, user.tenant_id)
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "email": email, "projects": projects}
    )


@router.post("/projects")
async def create_project_(
    request: Request,
    slug: str = Form(...),
    name: str = Form(...),
    email: str = Depends(require_session_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _user(session, email)
    await create_project(session, user.tenant_id, slug=slug, name=name)
    return RedirectResponse("/app", status_code=303)


@router.get("/projects/{slug}", response_class=HTMLResponse)
async def project_view(
    slug: str,
    request: Request,
    email: str = Depends(require_session_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _user(session, email)
    project = (
        await session.execute(
            select(Project).where(Project.tenant_id == user.tenant_id, Project.slug == slug)
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(404, "project not found")
    feedbacks = await list_feedbacks(session, project.id, limit=100)
    keys = (
        await session.execute(select(ApiKey).where(ApiKey.project_id == project.id))
    ).scalars().all()
    chats = await list_chat_links(session, project.id)
    stats = await stats_for_project(session, project.id)
    flash_key = request.session.pop("new_key", None)
    flash_link = request.session.pop("new_chat_link", None)
    return templates.TemplateResponse(
        "project.html",
        {
            "request": request,
            "email": email,
            "project": project,
            "feedbacks": feedbacks,
            "keys": keys,
            "chats": chats,
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
    email: str = Depends(require_session_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _user(session, email)
    project = (
        await session.execute(
            select(Project).where(Project.tenant_id == user.tenant_id, Project.slug == slug)
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(404, "project not found")
    _, full = await issue_api_key(session, project.id, label=label)
    request.session["new_key"] = full
    return RedirectResponse(f"/app/projects/{slug}", status_code=303)


@router.post("/projects/{slug}/chat-links")
async def create_chat_link_(
    slug: str,
    request: Request,
    email: str = Depends(require_session_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _user(session, email)
    project = (
        await session.execute(
            select(Project).where(Project.tenant_id == user.tenant_id, Project.slug == slug)
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(404, "project not found")
    token = await issue_chat_link_token(session, project.id, created_by_email=email)
    bot_user = os.getenv("FEEDBOT_TELEGRAM_BOT_USERNAME", "")
    deep_link = (
        f"https://t.me/{bot_user}?startgroup=link_{token.token}" if bot_user else ""
    )
    request.session["new_chat_link"] = {
        "token": token.token,
        "deep_link": deep_link,
        "expires_at": token.expires_at.isoformat(),
    }
    return RedirectResponse(f"/app/projects/{slug}", status_code=303)


@router.post("/projects/{slug}/chat-links/{link_id}/delete")
async def delete_chat_link_(
    slug: str,
    link_id: int,
    email: str = Depends(require_session_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _user(session, email)
    project = (
        await session.execute(
            select(Project).where(Project.tenant_id == user.tenant_id, Project.slug == slug)
        )
    ).scalar_one_or_none()
    if not project:
        raise HTTPException(404, "project not found")
    await unlink_chat(session, project.id, link_id)
    return RedirectResponse(f"/app/projects/{slug}", status_code=303)
