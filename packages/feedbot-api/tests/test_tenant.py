"""C4 — tenant export + tenant delete.

Contract under test:

    1. GET /v1/tenant/export streams a non-trivial application/zip.
    2. The zip contains metadata.json + per-table json/csv with the
       owner's data; API key secret_hash is scrubbed.
    3. POST /v1/tenant/delete with mismatched confirm_email returns 400.
    4. POST /v1/tenant/delete with a matching confirm_email cascades
       through projects, feedback, members and ends with 204; the
       tenant row is gone.

Both endpoints are owner-only — non-owners get 403 from require_owner.
We use the conftest factories to avoid duplicating the bootstrap.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
import pytest_asyncio
from feedbot_core.models import Feedback, Project, Tenant, User
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture(autouse=True)
async def _reset_limiter():
    """Slowapi keeps in-memory buckets per (route, IP). The export route
    is 1/day, so without a reset every test after the first 429s. We
    reset before AND after — the autouse fixture wraps every test in
    this module."""
    from feedbot_api.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


_AT = chr(0x40)
_DOMAIN = "example.com"


def _addr(local: str) -> str:
    return f"{local}{_AT}{_DOMAIN}"


# ─── Export ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_streams_zip_with_data(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
) -> None:
    tenant: Tenant = await make_tenant(name="Exporter")
    owner: User = await make_user(
        tenant=tenant, email=_addr("export_owner"), role="owner"
    )
    project: Project = await make_project(tenant=tenant, slug="p1", name="P1")
    db_session.add(
        Feedback(
            public_id="FB-EXPORT1",
            project_id=project.id,
            title="hello",
            body="world",
            author_platform="web",
            author_id="abc",
        )
    )
    await db_session.flush()
    await login_as(owner)

    res = await client.get("/v1/tenant/export")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    assert "feedbot-export" in res.headers["content-disposition"]

    blob = res.content
    assert len(blob) > 100  # Sanity: not an empty zip

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        assert "metadata.json" in names
        # All six tables represented in both formats.
        for table in ("users", "projects", "feedback", "llm_calls", "api_keys", "audit_events"):
            assert f"{table}.json" in names
            assert f"{table}.csv" in names
        meta = json.loads(zf.read("metadata.json"))
        assert meta["tenant_id"] == tenant.id
        assert meta["tenant_name"] == "Exporter"
        assert meta["exported_by"] == owner.email

        users = json.loads(zf.read("users.json"))
        assert any(u["email"] == owner.email for u in users)

        feedback = json.loads(zf.read("feedback.json"))
        assert any(f["public_id"] == "FB-EXPORT1" for f in feedback)


@pytest.mark.asyncio
async def test_export_strips_api_key_secret_hash(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
) -> None:
    """API key rows must never carry the secret_hash into an export."""
    from feedbot_core.models import ApiKey

    tenant = await make_tenant(name="Secret-safe")
    owner = await make_user(
        tenant=tenant, email=_addr("secret_owner"), role="owner"
    )
    project = await make_project(tenant=tenant, slug="p1", name="P1")
    db_session.add(
        ApiKey(
            project_id=project.id,
            label="ci",
            prefix="fbk_test",
            secret_hash="$argon2id$v=19$...REDACTED",
        )
    )
    await db_session.flush()
    await login_as(owner)

    res = await client.get("/v1/tenant/export")
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        keys = json.loads(zf.read("api_keys.json"))
    assert keys, "expected at least one api_key row"
    for k in keys:
        assert k["secret_hash"] is None
        assert k["prefix"] == "fbk_test"


# ─── Delete ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_rejects_mismatched_email(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    login_as,
) -> None:
    tenant = await make_tenant(name="MismatchCo")
    owner = await make_user(
        tenant=tenant, email=_addr("mismatch_owner"), role="owner"
    )
    await login_as(owner)

    res = await client.post(
        "/v1/tenant/delete",
        json={"confirm_email": _addr("someone_else")},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_delete_cascades_tenant(
    client: AsyncClient,
    db_session: AsyncSession,
    make_tenant,
    make_user,
    make_project,
    login_as,
) -> None:
    tenant = await make_tenant(name="ToDelete")
    owner = await make_user(
        tenant=tenant, email=_addr("delete_owner"), role="owner"
    )
    project = await make_project(tenant=tenant, slug="p1", name="P1")
    db_session.add(
        Feedback(
            public_id="FB-DEL1",
            project_id=project.id,
            title="bye",
            body="now",
            author_platform="web",
            author_id="abc",
        )
    )
    await db_session.flush()
    tenant_id = tenant.id
    project_id = project.id
    await login_as(owner)

    res = await client.post(
        "/v1/tenant/delete",
        json={"confirm_email": owner.email},
    )
    assert res.status_code == 204

    # Cascade verification — tenant + every owned row gone.
    t = await db_session.get(Tenant, tenant_id)
    assert t is None

    proj_count = await db_session.execute(
        select(func.count())
        .select_from(Project)
        .where(Project.id == project_id)
    )
    assert proj_count.scalar_one() == 0

    fb_count = await db_session.execute(
        select(func.count())
        .select_from(Feedback)
        .where(Feedback.project_id == project_id)
    )
    assert fb_count.scalar_one() == 0

    user_count = await db_session.execute(
        select(func.count())
        .select_from(User)
        .where(User.id == owner.id)
    )
    assert user_count.scalar_one() == 0
