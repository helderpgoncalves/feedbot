"""Public invite-acceptance endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from feedbot_core.repos import get_invite_by_token, redeem_invite
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session
from feedbot_api.rate_limit import limiter
from feedbot_api.templating import render

router = APIRouter(tags=["invites"])


@router.get("/invites/{token}", response_class=HTMLResponse)
async def invite_landing(request: Request, token: str, session: AsyncSession = Depends(get_session)) -> Response:
    invite = await get_invite_by_token(session, token)
    valid = bool(invite and invite.used_at is None)
    return render(request, "invite_accept.html", {"invite": invite, "valid": valid})


@router.post("/invites/{token}")
@limiter.limit("5/15minutes")
async def invite_accept(request: Request, token: str, session: AsyncSession = Depends(get_session)) -> Response:
    user = await redeem_invite(session, token)
    if not user:
        return render(
            request,
            "invite_accept.html",
            {"invite": None, "valid": False, "error": "invalid or expired"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    request.session["email"] = user.email
    return RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
