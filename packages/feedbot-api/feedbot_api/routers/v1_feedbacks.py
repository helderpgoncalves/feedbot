"""Cookie-authed feedback endpoints — consumed by the dashboard SPA.

The bot and external clients keep using the API-key-authed ``/v1/feedbacks*``
in ``v1.py``; this router speaks the same shapes but goes through
``require_project_access`` (cookie session) so the SPA can call it without
needing an API key.

Routes are scoped to the project slug — there is no global
``/v1/feedbacks`` for the dashboard, because the dashboard always operates
within a project context.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from feedbot_core import audit
from feedbot_core.models import Feedback, FeedbackStatus, FeedbackType, Project, Severity, User
from feedbot_core.repos import (
    get_feedback_by_public_id,
    list_feedbacks,
    stats_for_project,
    update_feedback_status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import client_ip, client_user_agent
from feedbot_api.deps import get_session, require_project_access
from feedbot_api.schemas import FeedbackOut, FeedbackPatch, StatsOut

log = logging.getLogger("feedbot.v1.feedbacks")

router = APIRouter(prefix="/v1", tags=["v1.feedbacks"])


def _to_out(fb: Feedback, project: Project) -> FeedbackOut:
    return FeedbackOut(
        id=fb.public_id,
        project_slug=project.slug,
        type=fb.type,
        severity=fb.severity,
        status=fb.status,
        title=fb.title,
        body=fb.body,
        summary=fb.summary,
        tags=fb.tags,
        author_platform=fb.author_platform,
        author_name=fb.author_name,
        note=fb.note,
        reply_to_user=fb.reply_to_user,
        user_reply=fb.user_reply,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
    )


@router.get(
    "/projects/{slug}/feedbacks",
    response_model=list[FeedbackOut],
    summary="List feedback in a project (filterable)",
)
async def list_(
    slug: str,
    status: FeedbackStatus | None = None,
    type: FeedbackType | None = None,
    severity: Severity | None = None,
    limit: int = Query(50, ge=1, le=200),
    pair: tuple[User, Project] = Depends(require_project_access),
    session: AsyncSession = Depends(get_session),
) -> list[FeedbackOut]:
    _me, project = pair
    rows = await list_feedbacks(
        session,
        project.id,
        status=status,
        type=type,
        severity=severity,
        limit=limit,
    )
    return [_to_out(r, project) for r in rows]


@router.get(
    "/projects/{slug}/feedbacks/{public_id}",
    response_model=FeedbackOut,
    summary="Get one feedback by FB-XXXXXX",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Feedback not in this project."}},
)
async def get_(
    slug: str,
    public_id: str,
    pair: tuple[User, Project] = Depends(require_project_access),
    session: AsyncSession = Depends(get_session),
) -> FeedbackOut:
    _me, project = pair
    fb = await get_feedback_by_public_id(session, project.id, public_id)
    if fb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "feedback not found")
    return _to_out(fb, project)


@router.patch(
    "/projects/{slug}/feedbacks/{public_id}",
    response_model=FeedbackOut,
    summary="Update status / append a note / queue a reply",
    responses={status.HTTP_404_NOT_FOUND: {"description": "Feedback not in this project."}},
)
async def patch_(
    slug: str,
    public_id: str,
    request: Request,
    body: FeedbackPatch,
    pair: tuple[User, Project] = Depends(require_project_access),
    session: AsyncSession = Depends(get_session),
) -> FeedbackOut:
    me, project = pair
    fb = await get_feedback_by_public_id(session, project.id, public_id)
    if fb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "feedback not found")

    changed: dict[str, object] = {}
    if body.status is not None and body.status != fb.status:
        await update_feedback_status(session, fb, body.status, body.note)
        changed["status"] = str(body.status)
    elif body.note:
        # Note-only update — preserve current status.
        await update_feedback_status(session, fb, fb.status, body.note)
        changed["note"] = True

    if body.reply_to_user is not None:
        fb.reply_to_user = body.reply_to_user
        await session.flush()
        await session.refresh(fb, attribute_names=["updated_at"])
        changed["reply_to_user"] = True

    if changed:
        await audit.log_event(
            session,
            event="feedback.updated",
            tenant_id=me.tenant_id,
            user_id=me.id,
            project_id=project.id,
            ip=client_ip(request),
            user_agent=client_user_agent(request),
            details={"public_id": public_id, **changed},
        )

    return _to_out(fb, project)


@router.get(
    "/projects/{slug}/feedbacks-stats",
    response_model=StatsOut,
    summary="Counts grouped by status (cookie-authed)",
)
async def stats_(
    slug: str,
    pair: tuple[User, Project] = Depends(require_project_access),
    session: AsyncSession = Depends(get_session),
) -> StatsOut:
    _me, project = pair
    by_status = await stats_for_project(session, project.id)
    return StatsOut(by_status=by_status, total=sum(by_status.values()))
