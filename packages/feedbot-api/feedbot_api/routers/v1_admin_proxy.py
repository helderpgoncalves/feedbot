"""Admin → Domain & HTTPS endpoints.

Owner-only, self-host only. Each handler delegates to the
orchestrator (which talks to the Caddy admin API on
``feedbot_net``) — see ``feedbot_api/orchestrator/__init__.py``.

Two-phase UX:

1. **Pre-flight** — ``POST /dns-check`` resolves the domain
   client-side without persisting anything. Used by the SPA's
   "Validate DNS" button before the user commits.

2. **Apply** — ``POST /config`` writes to ``instance_config``,
   pushes a fresh Caddy config blob, and returns immediately.
   Caddy starts the ACME flow asynchronously; the SPA polls
   ``GET /status`` every ~3s until ``configured`` is true.

Security boundaries:

- ``require_self_host`` 404s the whole surface on cloud builds.
- All endpoints are owner-only.
- ``letsencrypt_email`` is the only PII we ask for — recorded in
  the audit trail under ``admin.system.proxy.apply``, *not*
  redacted, because LE-issued certs are public information
  anyway and operators need a paper trail.
"""

from __future__ import annotations

import logging
import socket

from fastapi import APIRouter, Depends, HTTPException, Request, status
from feedbot_core.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import client_ip, client_user_agent
from feedbot_api.deps import get_session, require_owner, require_self_host
from feedbot_api.orchestrator import (
    Orchestrator,
)
from feedbot_api.orchestrator import (
    caddy as orch_caddy,
)
from feedbot_api.orchestrator import (
    settings as orch_settings,
)
from feedbot_api.schemas import (
    ProxyConfigIn,
    ProxyConfigOut,
    ProxyDnsCheckIn,
    ProxyDnsCheckOut,
    ProxyStatusOut,
)

log = logging.getLogger("feedbot.v1.admin.proxy")


router = APIRouter(
    prefix="/v1/admin/proxy",
    tags=["v1.admin"],
    dependencies=[Depends(require_self_host)],
)


def _to_out(s: orch_settings.InstanceSettings) -> ProxyConfigOut:
    return ProxyConfigOut(
        domain=s.proxy.domain,
        letsencrypt_email=s.proxy.letsencrypt_email,
        https_enabled=s.proxy.https_enabled,
        configured=bool(s.proxy.domain and s.proxy.letsencrypt_email),
    )


def _resolve_server_ip() -> str | None:
    """Best-effort lookup of the host's outbound IP.

    We open a UDP socket to a public address (no packets sent —
    ``connect`` on UDP only sets the routing table entry) and read
    the kernel-assigned local IP. Returns ``None`` on any failure
    so the caller can render "unknown" rather than 500-ing.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            s.connect(("8.8.8.8", 53))
            return s.getsockname()[0]
    except OSError:
        return None


@router.get(
    "/config",
    response_model=ProxyConfigOut,
    summary="Read the persisted domain / TLS config (owner only).",
)
async def get_config(
    _me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ProxyConfigOut:
    s = await orch_settings.load(session)
    return _to_out(s)


@router.post(
    "/config",
    response_model=ProxyConfigOut,
    summary="Set the domain + LE email and push a TLS Caddy config (owner only).",
    responses={
        status.HTTP_502_BAD_GATEWAY: {
            "description": "Caddy admin API rejected the new config or was unreachable."
        },
    },
)
async def post_config(
    body: ProxyConfigIn,
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ProxyConfigOut:
    orch = Orchestrator(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    try:
        s = await orch.apply_proxy(
            domain=body.domain.strip().lower(),
            letsencrypt_email=body.letsencrypt_email.strip(),
        )
    except orch_caddy.CaddyError as exc:
        # The DB row was rolled back inside apply_proxy on failure;
        # surface a 502 so the SPA can render the underlying admin
        # API error in the chip.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"caddy reload failed: {exc}"
        ) from exc
    return _to_out(s)


@router.delete(
    "/config",
    response_model=ProxyConfigOut,
    summary="Clear the domain and revert Caddy to IP-only mode (owner only).",
)
async def delete_config(
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ProxyConfigOut:
    orch = Orchestrator(
        session,
        user_id=me.id,
        tenant_id=me.tenant_id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    try:
        s = await orch.clear_proxy()
    except orch_caddy.CaddyError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"caddy reload failed: {exc}"
        ) from exc
    return _to_out(s)


@router.get(
    "/status",
    response_model=ProxyStatusOut,
    summary="Polled view of cert provisioning state (owner only).",
)
async def get_status(
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> ProxyStatusOut:
    """Polled by the SPA every ~3s while a domain change is applying.

    Always returns 200 — Caddy admin errors land in ``error`` so
    the UI can render the chip without distinguishing an HTTP 200
    "no domain" from a 502 "admin API down".
    """
    orch = Orchestrator(session, user_id=me.id, tenant_id=me.tenant_id)
    info = await orch.proxy_status()
    return ProxyStatusOut(
        domain=info.get("domain"),
        configured=bool(info.get("configured")),
        https_enabled=bool(info.get("https_enabled")),
        policy_count=info.get("policy_count"),
        error=info.get("error"),
    )


@router.post(
    "/dns-check",
    response_model=ProxyDnsCheckOut,
    summary="Pre-flight DNS check (owner only). Never persisted.",
)
async def dns_check(
    body: ProxyDnsCheckIn,
    _me: User = Depends(require_owner),
) -> ProxyDnsCheckOut:
    """Resolve ``domain`` and compare against the host's outbound IP.

    The match is a *hint*, not a hard block — propagation lag and
    NAT make false negatives common. The SPA shows a warning
    (not an error) when ``matches`` is false and lets the user
    proceed anyway.
    """
    domain = body.domain.strip().lower()
    server_ip = _resolve_server_ip()
    try:
        # ``getaddrinfo`` returns (family, type, proto, canonname, sockaddr).
        # ``sockaddr[0]`` is the IP for both AF_INET and AF_INET6.
        infos = socket.getaddrinfo(domain, None)
    except socket.gaierror as exc:
        return ProxyDnsCheckOut(
            domain=domain,
            resolved_ips=[],
            server_ip=server_ip,
            matches=False,
            error=str(exc),
        )

    resolved = sorted({info[4][0] for info in infos})
    matches = bool(server_ip and server_ip in resolved)
    return ProxyDnsCheckOut(
        domain=domain,
        resolved_ips=resolved,
        server_ip=server_ip,
        matches=matches,
    )
