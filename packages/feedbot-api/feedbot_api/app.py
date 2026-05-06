from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from feedbot_core.settings import CoreSettings
from starlette.middleware.sessions import SessionMiddleware

from feedbot_api.routers import auth, dashboard, internal, v1
from feedbot_api.templating import templates

settings = CoreSettings()
app = FastAPI(title="Feedbot", version="0.1.0")

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=False)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(v1.router)
app.include_router(internal.router)
app.include_router(auth.router)
app.include_router(dashboard.router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/healthz")
async def healthz():
    return {"ok": True}
