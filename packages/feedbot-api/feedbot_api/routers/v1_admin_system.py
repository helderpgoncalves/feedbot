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
from feedbot_core.models import User
from feedbot_core.repos import update_instance_config
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import client_ip, client_user_agent
from feedbot_api.deps import get_session, require_owner, require_self_host
from feedbot_api.orchestrator import (
    Orchestrator,
    audit as orch_audit,
    autostart as orch_autostart,
    compose as orch_compose,
    settings as orch_settings,
)
from feedbot_api.schemas import (
    AutostartStatusOut,
    SystemRestartIn,
    SystemServiceOut,
    SystemStatusOut,
    TelemetryConfigIn,
    TelemetryConfigOut,
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
