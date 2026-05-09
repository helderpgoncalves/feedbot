"""GDPR endpoints — data export and tenant deletion.

The export endpoint streams a single ZIP that contains every row a
tenant owns (feedback, users, projects, llm_calls, audit log, API key
metadata). Deliberately not paginated — at our target tenant size
(<1M feedback) the whole archive fits comfortably under 100 MB
uncompressed and Stripe-portal-style "click to download" UX is the
expected pattern.

Tenant deletion is irreversible. We use email-reconfirm at the API
boundary — the SPA sends the owner's current email back as proof of
intent (the cookie-only auth path means a CSRF would otherwise be
sufficient, and "delete my workspace" deserves more friction than
"create a project").
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from feedbot_core import audit
from feedbot_core.billing import is_billing_enabled
from feedbot_core.models import (
    ApiKey,
    AuditEvent,
    Feedback,
    LLMCall,
    Project,
    Tenant,
    User,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from feedbot_api.cookies import client_ip, client_user_agent
from feedbot_api.deps import get_session, require_owner
from feedbot_api.rate_limit import limiter

log = logging.getLogger("feedbot.v1.tenant")

router = APIRouter(prefix="/v1", tags=["v1.tenant"])


# ─── Helpers ────────────────────────────────────────────────────────────────


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy ORM row to a JSON-safe dict.

    Keeps datetimes as ISO strings, stringifies enums, drops bytes (we
    never want to leak encrypted blobs into an export).
    """
    out: dict[str, Any] = {}
    for c in row.__table__.columns:
        v = getattr(row, c.name)
        if isinstance(v, datetime):
            out[c.name] = v.isoformat()
        elif isinstance(v, bytes):
            # Encrypted blobs (LargeBinary) — never export.
            out[c.name] = None
        else:
            out[c.name] = v
    return out


def _to_csv(rows: list[dict[str, Any]]) -> str:
    """Render a list of dicts to CSV. Empty list  >>>  empty string."""
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()


# ─── GET /v1/tenant/export ─────────────────────────────────────────────────


@router.get(
    "/tenant/export",
    summary="Stream a ZIP of every row this tenant owns (owner only)",
    responses={
        status.HTTP_200_OK: {
            "description": "application/zip stream — Content-Disposition includes the timestamp."
        },
    },
)
@limiter.limit("1/day")
async def export_tenant(
    request: Request,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """GDPR data-export. Streams one zip with the per-table dumps.

    Performance: we materialise everything into memory before zipping
    because (a) `zipfile.ZipFile` doesn't support streaming writes from
    async iterators without extra glue, and (b) at our target volume
    the whole archive fits well under available RAM. If volumes grow,
    swap this for chunked NDJSON + a streaming zip writer (zipstream).
    """
    tenant = await session.get(Tenant, me.tenant_id)
    if tenant is None:
        # Should be impossible — require_owner verified the session.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")

    # Pull every owned table.
    users_rows = (
        await session.execute(select(User).where(User.tenant_id == me.tenant_id))
    ).scalars().all()
    projects_rows = (
        await session.execute(
            select(Project).where(Project.tenant_id == me.tenant_id)
        )
    ).scalars().all()
    project_ids = [p.id for p in projects_rows]
    feedback_rows = (
        await session.execute(
            select(Feedback).where(
                Feedback.project_id.in_(project_ids) if project_ids else False
            )
        )
        if project_ids
        else None
    )
    feedbacks: list[Feedback] = (
        feedback_rows.scalars().all() if feedback_rows is not None else []
    )
    llm_rows: list[LLMCall] = (
        (
            await session.execute(
                select(LLMCall).where(LLMCall.project_id.in_(project_ids))
            )
        ).scalars().all()
        if project_ids
        else []
    )
    api_keys_rows: list[ApiKey] = (
        (
            await session.execute(
                select(ApiKey).where(ApiKey.project_id.in_(project_ids))
            )
        ).scalars().all()
        if project_ids
        else []
    )
    audit_rows = (
        await session.execute(
            select(AuditEvent).where(AuditEvent.tenant_id == me.tenant_id)
        )
    ).scalars().all()

    # Build the dicts. Strip API key secrets — only prefix + metadata.
    users = [_row_to_dict(u) for u in users_rows]
    projects = [_row_to_dict(p) for p in projects_rows]
    feedback = [_row_to_dict(f) for f in feedbacks]
    llm_calls = [_row_to_dict(l) for l in llm_rows]
    api_keys = [
        {**_row_to_dict(k), "secret_hash": None} for k in api_keys_rows
    ]
    audit_events = [_row_to_dict(a) for a in audit_rows]

    # Build the zip in memory.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "metadata.json",
            json.dumps(
                {
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "exported_at": datetime.now(UTC).isoformat(),
                    "exported_by": me.email,
                    "schema_version": 1,
                },
                indent=2,
            ),
        )
        for name, rows in (
            ("users", users),
            ("projects", projects),
            ("feedback", feedback),
            ("llm_calls", llm_calls),
            ("api_keys", api_keys),
            ("audit_events", audit_events),
        ):
            zf.writestr(f"{name}.json", json.dumps(rows, indent=2))
            zf.writestr(f"{name}.csv", _to_csv(rows))

    payload = buf.getvalue()

    await audit.log_event(
        session,
        event="tenant.exported",
        tenant_id=me.tenant_id,
        user_id=me.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={
            "rows": {
                "users": len(users),
                "projects": len(projects),
                "feedback": len(feedback),
                "llm_calls": len(llm_calls),
                "api_keys": len(api_keys),
                "audit_events": len(audit_events),
            }
        },
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"feedbot-export-{tenant.id}-{stamp}.zip"

    async def _stream() -> AsyncIterator[bytes]:
        # Stream in 64 KiB chunks so very large exports don't sit in
        # the proxy buffer all at once.
        chunk = 64 * 1024
        for i in range(0, len(payload), chunk):
            yield payload[i : i + chunk]

    return StreamingResponse(
        _stream(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── POST /v1/tenant/delete ────────────────────────────────────────────────


class DeleteTenantIn(BaseModel):
    """Body for ``POST /v1/tenant/delete``.

    The owner re-types their own email as deliberate-friction. Anything
    else returns 400; a CSRF that magically guesses the owner's email
    is already a much bigger problem than we're trying to solve here.
    """

    confirm_email: str = Field(min_length=3, max_length=255)


@router.post(
    "/tenant/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete this tenant and all its data (owner only)",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "confirm_email did not match the signed-in owner."
        },
    },
)
@limiter.limit("3/hour")
async def delete_tenant(
    request: Request,
    body: DeleteTenantIn,
    me: User = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Cascade-delete every row this tenant owns. Best-effort cancels
    the Stripe subscription if billing is enabled.

    The audit log row for ``tenant.deleted`` is written *before* the
    tenant cascade so it survives the delete (ON DELETE SET NULL on
    audit_events.tenant_id keeps the row but nulls the FK).
    """
    if body.confirm_email.lower().strip() != me.email.lower().strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "confirm_email mismatch"
        )

    tenant = await session.get(Tenant, me.tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")

    # Best-effort Stripe cancel. Failures here are logged, not raised —
    # the local delete must succeed regardless.
    if is_billing_enabled():
        from feedbot_core.billing.stripe_client import (
            StripeError,
            cancel_subscription,
        )
        from feedbot_core.repos import get_subscription_for_tenant

        sub = await get_subscription_for_tenant(session, me.tenant_id)
        if sub and sub.stripe_subscription_id:
            try:
                await cancel_subscription(
                    sub.stripe_subscription_id, at_period_end=False
                )
            except StripeError as exc:
                log.warning(
                    "stripe_cancel_during_delete_failed tenant=%s err=%s",
                    me.tenant_id,
                    exc,
                )

    await audit.log_event(
        session,
        event="tenant.deleted",
        tenant_id=me.tenant_id,
        user_id=me.id,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
        details={"tenant_name": tenant.name, "owner_email": me.email},
    )

    # Cascade — relationship config on Tenant takes care of users,
    # projects (and projects' children: feedback, api_keys, members,
    # chats), and the singleton subscription.
    await session.delete(tenant)
    await session.flush()
