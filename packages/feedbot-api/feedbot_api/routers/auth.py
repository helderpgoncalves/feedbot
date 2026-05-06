import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from feedbot_core.repos import consume_magic_link, get_or_create_user, issue_magic_link
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.deps import get_session
from feedbot_api.templating import templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_submit(
    request: Request, email: str = Form(...), session: AsyncSession = Depends(get_session)
):
    raw = secrets.token_urlsafe(24)
    await issue_magic_link(session, email, raw)
    base = str(request.base_url).rstrip("/")
    link = f"{base}/login/verify?email={email}&token={raw}"
    # Console backend: print link for the dev to copy.
    print(f"\n[feedbot] magic link for {email}: {link}\n", flush=True)
    return templates.TemplateResponse("login_sent.html", {"request": request, "email": email})


@router.get("/login/verify")
async def login_verify(
    request: Request, email: str, token: str, session: AsyncSession = Depends(get_session)
):
    ok = await consume_magic_link(session, email, token)
    if not ok:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "invalid or expired link"}, status_code=400
        )
    await get_or_create_user(session, email)
    request.session["email"] = email
    return RedirectResponse("/app", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
