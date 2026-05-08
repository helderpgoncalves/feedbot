"""HTTP tests for the backups + updates surface on /v1/admin/system.

Backups: ``orch_backup.create_backup`` is mocked at the module
boundary so we never shell out to ``docker compose exec pg_dump``;
listing + download exercise the real filesystem code with
``FEEDBOT_BACKUPS_DIR`` pointed at a tmp dir.

Updates: ``orch_updates.check`` and ``Orchestrator.upgrade`` are
mocked. The HTTP contract is what's being tested here — the GHCR
parsing logic gets unit-tested separately in ``test_orchestrator``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from feedbot_core.models import Role

# ── auth + cloud short-circuit ──────────────────────────────────────


@pytest.mark.asyncio
async def test_backups_requires_login(client):
    resp = await client.get("/v1/admin/system/backups")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_backups_admin_forbidden(
    client, db_session, make_tenant, make_user, login_as
):
    tenant = await make_tenant()
    admin = await make_user(tenant=tenant, email="a@x.com", role=Role.ADMIN)
    await login_as(admin)
    resp = await client.get("/v1/admin/system/backups")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_backups_cloud_returns_404(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    monkeypatch.setenv("FEEDBOT_DEPLOYMENT", "cloud")
    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)
    resp = await client.get("/v1/admin/system/backups")
    assert resp.status_code == 404


# ── Backups ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_backups_filters_to_pattern(
    client, db_session, make_tenant, make_user, login_as, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("FEEDBOT_BACKUPS_DIR", str(tmp_path))
    # One real backup, one decoy that should not show up.
    real = tmp_path / "feedbot-20260101T000000Z.tar.gz"
    real.write_bytes(b"x" * 10)
    decoy = tmp_path / "random-file.txt"
    decoy.write_bytes(b"")

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/system/backups")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["filename"] == "feedbot-20260101T000000Z.tar.gz"
    assert rows[0]["size_bytes"] == 10


@pytest.mark.asyncio
async def test_create_backup_calls_orchestrator(
    client, db_session, make_tenant, make_user, login_as, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("FEEDBOT_BACKUPS_DIR", str(tmp_path))

    from feedbot_api.orchestrator import backup

    rec = backup.BackupRecord(
        filename="feedbot-20260102T000000Z.tar.gz",
        path=tmp_path / "feedbot-20260102T000000Z.tar.gz",
        size_bytes=42,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    monkeypatch.setattr(backup, "create_backup", AsyncMock(return_value=rec))

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post("/v1/admin/system/backups")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "feedbot-20260102T000000Z.tar.gz"
    assert body["size_bytes"] == 42

    # Audit row landed.
    from feedbot_core.models import AuditEvent
    from sqlalchemy import select

    rows = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.event == "admin.system.backup.create")
        )
    ).scalars().all()
    assert any(rec.filename in (r.details or "") for r in rows)


@pytest.mark.asyncio
async def test_create_backup_502_on_failure(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import backup

    monkeypatch.setattr(
        backup, "create_backup", AsyncMock(side_effect=backup.BackupError("dump exit 1"))
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post("/v1/admin/system/backups")
    assert resp.status_code == 502
    assert "dump" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_download_backup_streams_file(
    client, db_session, make_tenant, make_user, login_as, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("FEEDBOT_BACKUPS_DIR", str(tmp_path))
    target = tmp_path / "feedbot-20260103T000000Z.tar.gz"
    target.write_bytes(b"PAYLOAD")

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get(
        f"/v1/admin/system/backups/{target.name}/download"
    )
    assert resp.status_code == 200, resp.text
    assert resp.content == b"PAYLOAD"
    assert resp.headers["content-type"] == "application/gzip"


@pytest.mark.asyncio
async def test_download_backup_rejects_path_traversal(
    client, db_session, make_tenant, make_user, login_as, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("FEEDBOT_BACKUPS_DIR", str(tmp_path))

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    # ``..`` and explicit slashes both rejected by get_backup.
    resp = await client.get(
        "/v1/admin/system/backups/feedbot-..%2Fetc%2Fpasswd.tar.gz/download"
    )
    assert resp.status_code == 404


# ── Updates ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_updates_get_reports_available(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import updates

    monkeypatch.setattr(
        updates,
        "check",
        AsyncMock(
            return_value=updates.UpdateInfo(
                current="v1.0.0", latest="v1.2.3", available=True
            )
        ),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/system/updates")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "current": "v1.0.0",
        "latest": "v1.2.3",
        "available": True,
        "error": None,
    }


@pytest.mark.asyncio
async def test_updates_get_passes_through_error(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import updates

    monkeypatch.setattr(
        updates,
        "check",
        AsyncMock(
            return_value=updates.UpdateInfo(
                current="dev", latest=None, available=False, error="ghcr down"
            )
        ),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.get("/v1/admin/system/updates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["error"] == "ghcr down"


@pytest.mark.asyncio
async def test_updates_apply_calls_compose(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import compose

    pull = AsyncMock()
    up = AsyncMock()
    monkeypatch.setattr(compose, "pull", pull)
    monkeypatch.setattr(compose, "up", up)

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post("/v1/admin/system/updates/apply")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    pull.assert_awaited_once()
    up.assert_awaited_once()


@pytest.mark.asyncio
async def test_updates_apply_502_on_compose_error(
    client, db_session, make_tenant, make_user, login_as, monkeypatch
):
    from feedbot_api.orchestrator import compose

    monkeypatch.setattr(
        compose,
        "pull",
        AsyncMock(
            side_effect=compose.ComposeError(
                args=["pull"], returncode=1, stderr="registry unreachable"
            )
        ),
    )

    tenant = await make_tenant()
    owner = await make_user(tenant=tenant, email="o@x.com", role=Role.OWNER)
    await login_as(owner)

    resp = await client.post("/v1/admin/system/updates/apply")
    assert resp.status_code == 502
    assert "registry" in resp.json()["detail"]
