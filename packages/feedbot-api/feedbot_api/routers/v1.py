from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_api_key, get_project_from_key, get_session
from feedbot_api.schemas import FeedbackIn, FeedbackOut, FeedbackPatch, StatsOut
from feedbot_core.models import ApiKey, Feedback, FeedbackStatus, FeedbackType, Project, Severity
from feedbot_core.repos import (
    create_feedback,
    get_feedback_by_public_id,
    list_feedbacks,
    stats_for_project,
    update_feedback_status,
)

router = APIRouter(prefix="/v1", tags=["v1"])


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


@router.get("/feedbacks", response_model=list[FeedbackOut])
async def list_(
    status: FeedbackStatus | None = None,
    type: FeedbackType | None = None,
    severity: Severity | None = None,
    limit: int = Query(50, ge=1, le=200),
    project: Project = Depends(get_project_from_key),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_feedbacks(
        session, project.id, status=status, type=type, severity=severity, limit=limit
    )
    return [_to_out(r, project) for r in rows]


@router.post("/feedbacks", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def create_(
    body: FeedbackIn,
    key: ApiKey = Depends(get_api_key),
    project: Project = Depends(get_project_from_key),
    session: AsyncSession = Depends(get_session),
):
    if key.scope == "read":
        raise HTTPException(403, "read-only key")
    fb = await create_feedback(
        session,
        project_id=project.id,
        title=body.title,
        body=body.body,
        type=body.type,
        severity=body.severity,
        author_platform=body.author_platform,
        author_id=body.author_id,
        author_name=body.author_name,
    )
    return _to_out(fb, project)


@router.get("/feedbacks/{public_id}", response_model=FeedbackOut)
async def get_(
    public_id: str,
    project: Project = Depends(get_project_from_key),
    session: AsyncSession = Depends(get_session),
):
    fb = await get_feedback_by_public_id(session, project.id, public_id)
    if not fb:
        raise HTTPException(404, "feedback not found")
    return _to_out(fb, project)


@router.patch("/feedbacks/{public_id}", response_model=FeedbackOut)
async def patch_(
    public_id: str,
    body: FeedbackPatch,
    key: ApiKey = Depends(get_api_key),
    project: Project = Depends(get_project_from_key),
    session: AsyncSession = Depends(get_session),
):
    if key.scope == "read":
        raise HTTPException(403, "read-only key")
    fb = await get_feedback_by_public_id(session, project.id, public_id)
    if not fb:
        raise HTTPException(404, "feedback not found")
    if body.status is not None:
        await update_feedback_status(session, fb, body.status, body.note)
    elif body.note:
        fb.note = (fb.note + "\n" if fb.note else "") + body.note
    if body.reply_to_user is not None:
        fb.reply_to_user = body.reply_to_user
    return _to_out(fb, project)


@router.get("/stats", response_model=StatsOut)
async def stats_(
    project: Project = Depends(get_project_from_key),
    session: AsyncSession = Depends(get_session),
):
    by_status = await stats_for_project(session, project.id)
    return StatsOut(by_status=by_status, total=sum(by_status.values()))
