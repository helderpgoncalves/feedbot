"""Admin → System endpoints (status, autostart, telemetry, restart).

Owner-only, self-host only. Read-only and toggle-style operations
that don't fit the bigger ``email`` / ``bot`` / ``proxy`` slices.

What's here (I8 scope):

- ``GET  /status``       — services + version snapshot, fed by
  ``docker compose ps`` via the orchestrator.
- ``POST /restart``      — restart all services or one.
- ``GET  /autostart``    — current systemd / launchd state.
- ``POST /autostart``    — enable/disable based on body flag.
- ``GET  /telemetry``    — current opt-in state from instance_config.
- ``POST /telemetry``    — toggle on/off.

Updates and Backups are deliberately *not* included yet — both
need orchestrator primitives (image-pull lifecycle, ``pg_dump``
runner, backup listing) that don't exist in I4. They'll land in
a follow-up phase.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from feedbot_core.models import User
from feedbot_core.repos import update_instance_config
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import client_ip, client_user_agent
from feedbot_api.deps import get_session, require_owner, require_self_host
from feedbot_api.orchestrator import (
    Orchestrator,
    audit as orch_audit,
    autostart as orch_autostart,
    backup as orch_backup,
    compose as orch_compose,
    settings as orch_settings,
    updates as orch_updates,
)
from feedbot_api.schemas import (
    AutostartStatusOut,
    BackupOut,
    SystemRestartIn,
    SystemServiceOut,
    SystemStatusOut,
    TelemetryConfigIn,
    TelemetryConfigOut,
    UpdateApplyOut,
    UpdatesOut,
)

log = logging.getLogger("feedbot.v1.admin.system")


router = APIRouter(
    prefix="/v1/admin/system",
    tags=["v1.admin"],
    dependencies=[Depends(require_self_host)],
)


def _version() -> str:
    """Best-effort version string for the ``status`` payload.

    Prefers the build-time SHA passed by CI (matches the footer on
    the SPA) and falls back to a stable placeholder so the field is
    always present.
    """
    return os.getenv("FEEDBOT_BUILD_SHA") or "dev"


def _parse_compose_ps(stdout: str) -> list[SystemServiceOut]:
    """Decode ``docker compose ps --format json``.

    Newer compose emits one JSON object per line (NDJSON); older
    versions emit a single JSON array. We accept either so the
    same code works from local dev to CI.
    """
    text = stdout.strip()
    if not text:
        return []
    rows: list[dict] = []
    if text.startswith("["):
        try:
            rows = json.loads(text)
        except json.JSONDecodeError:
            log.warning("compose ps: bad array JSON")
            return []
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                log.debug("compose ps: skipping bad line %r", line)

    out: list[SystemServiceOut] = []
    for row in rows:
        # Compose key casing changed across versions; accept both.
        name = row.get("Service") or row.get("Name") or "unknown"
        state = row.get("State") or "unknown"
        image = row.get("Image")
        # ``Status`` is the human-friendly description ("Up 5 minutes").
        ps_status = row.get("Status")
        out.append(
            SystemServiceOut(
                name=str(name),
                state=str(state),
                image=image,
                status=ps_status,
            )
        )
    return out


# ── Status ──────────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=SystemStatusOut,
    summary="Health snapshot from ``docker compose ps`` (owner only).",
)
async def get_status(
    _me: User = Depends(require_owner),
) -> SystemStatusOut:
    try:
        result = await orch_compose.ps()
    except orch_compose.ComposeError as exc:
        return SystemStatusOut(
            ok=False,
            version=_version(),
            services=[],
            error=str(exc),
        )

    services = _parse_compose_ps(result.stdout)
    ok = bool(services) and all(s.state == "running" for s in services)
    return SystemStatusOut(
        ok=ok,
        version=_version(),
        services=services,
    )


# ── Restart ─────────────────────────────────────────────────────────


@router.post(
    "/restart",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Restart all services or one (owner only).",
)
async def post_restart(
    body: SystemRestartIn,
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> None:
    orch = Orchestrator(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    try:
        await orch.restart_service(body.service)
    except orch_compose.ComposeError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"compose restart failed: {exc}"
        ) from exc


# ── Autostart ──────────────────────────────────────────────────────


def _autostart_to_out(s: orch_autostart.AutostartStatus) -> AutostartStatusOut:
    return AutostartStatusOut(
        platform=s.platform.value,
        enabled=s.enabled,
        unit_path=s.unit_path,
        manual_instructions=s.manual_instructions,
    )


@router.get(
    "/autostart",
    response_model=AutostartStatusOut,
    summary="Read autostart state (owner only).",
)
async def get_autostart(_me: User = Depends(require_owner)) -> AutostartStatusOut:
    return _autostart_to_out(orch_autostart.status())


@router.post(
    "/autostart",
    response_model=AutostartStatusOut,
    summary="Enable or disable autostart (owner only).",
)
async def post_autostart(
    body: TelemetryConfigIn,  # same shape: {enabled: bool}
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> AutostartStatusOut:
    orch = Orchestrator(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    try:
        result = await orch.set_autostart(enabled=body.enabled)
    except orch_autostart.AutostartError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"autostart toggle failed: {exc}"
        ) from exc
    return _autostart_to_out(result)


# ── Telemetry ──────────────────────────────────────────────────────


@router.get(
    "/telemetry",
    response_model=TelemetryConfigOut,
    summary="Current telemetry opt-in state (owner only).",
)
async def get_telemetry(
    _me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> TelemetryConfigOut:
    s = await orch_settings.load(session)
    return TelemetryConfigOut(enabled=s.system.telemetry_enabled)


@router.post(
    "/telemetry",
    response_model=TelemetryConfigOut,
    summary="Toggle telemetry opt-in (owner only).",
)
async def post_telemetry(
    body: TelemetryConfigIn,
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> TelemetryConfigOut:
    """Persist the toggle and audit it.

    Telemetry is opt-in (default off). We don't restart any service
    — the flag is read at telemetry-event-emit time, not boot.
    """
    await update_instance_config(
        session,
        updated_by=me.id,
        telemetry_enabled=body.enabled,
    )
    await orch_audit.config_changed(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        section="telemetry",
        fields={"telemetry_enabled": body.enabled},
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    return TelemetryConfigOut(enabled=body.enabled)


# ── Backups ────────────────────────────────────────────────────────


def _backup_to_out(rec: orch_backup.BackupRecord) -> BackupOut:
    return BackupOut(
        filename=rec.filename,
        size_bytes=rec.size_bytes,
        created_at=rec.created_at,
    )


@router.get(
    "/backups",
    response_model=list[BackupOut],
    summary="List backup tarballs in <workdir>/backups (owner only).",
)
async def list_backups(_me: User = Depends(require_owner)) -> list[BackupOut]:
    return [_backup_to_out(r) for r in orch_backup.list_backups()]


@router.post(
    "/backups",
    response_model=BackupOut,
    status_code=status.HTTP_201_CREATED,
    summary="Run pg_dump and create a fresh tar.gz backup (owner only).",
)
async def create_backup(
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> BackupOut:
    try:
        rec = await orch_backup.create_backup()
    except orch_backup.BackupError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"backup failed: {exc}"
        ) from exc

    # Audit so the operator has a paper trail of who pulled state
    # off the box. The filename is non-secret (it's just a
    # timestamp) so we record it verbatim.
    await orch_audit.system_action(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        action="backup.create",
        target=rec.filename,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    return _backup_to_out(rec)


@router.get(
    "/backups/{filename}/download",
    summary="Download a backup tarball (owner only).",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Unknown filename or path traversal attempt."}
    },
)
async def download_backup(
    filename: str,
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
):
    """Stream the tarball as ``application/gzip``.

    ``orch_backup.get_backup`` validates the filename matches our
    naming pattern and contains no path separators — anything else
    returns 404 instead of letting a directory-traversal attempt
    surface as a 500.
    """
    rec = orch_backup.get_backup(filename)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "backup not found")

    await orch_audit.system_action(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        action="backup.download",
        target=rec.filename,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    return FileResponse(
        rec.path,
        media_type="application/gzip",
        filename=rec.filename,
    )


# ── Updates ────────────────────────────────────────────────────────


@router.get(
    "/updates",
    response_model=UpdatesOut,
    summary="Compare the running version against GHCR's latest (owner only).",
)
async def get_updates(_me: User = Depends(require_owner)) -> UpdatesOut:
    info = await orch_updates.check()
    return UpdatesOut(
        current=info.current,
        latest=info.latest,
        available=info.available,
        error=info.error,
    )


@router.post(
    "/updates/apply",
    response_model=UpdateApplyOut,
    summary="Pull the latest images and recreate containers (owner only).",
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "description": "compose pull/up failed; see body for the underlying error."
        },
    },
)
async def post_apply_update(
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> UpdateApplyOut:
    """Trigger a rolling update: pull, recreate, migrations on boot.

    The api container's CMD is ``alembic upgrade head && uvicorn …``,
    so we don't run migrations here — recreating the container is
    enough. The route is best-effort: if pull or up fails we surface
    a 502 with the compose error so the operator can debug.
    """
    orch = Orchestrator(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    try:
        await orch.upgrade()
    except orch_compose.ComposeError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"upgrade failed: {exc}"
        ) from exc
    return UpdateApplyOut(ok=True, message="containers recreated")
