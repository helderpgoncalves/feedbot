"""Per-project membership: who from the tenant can see this project."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse, Response
from feedbot_core.models import Project, User
from feedbot_core.repos import (
    add_project_member,
    get_user_by_email,
    remove_project_member,
)
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session, require_project_admin

router = APIRouter(prefix="/app/projects/{slug}/members", tags=["members"])


@router.post("")
async def add_member(
    slug: str,
    email: str = Form(...),
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    me, project = pair
    target = await get_user_by_email(session, email.lower().strip())
    if not target or target.tenant_id != me.tenant_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "user must already exist in this tenant — invite them first under Team",
        )
    await add_project_member(session, project.id, target.id)
    return RedirectResponse(f"/app/projects/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/delete")
async def remove_member(
    slug: str,
    user_id: int,
    pair: tuple[User, Project] = Depends(require_project_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    _me, project = pair
    await remove_project_member(session, project.id, user_id)
    return RedirectResponse(f"/app/projects/{slug}", status_code=status.HTTP_303_SEE_OTHER)
