"""Smoke tests for the test infrastructure itself.

If these fail, the issue is in conftest.py — fix that before writing real
tests against this module.
"""

from __future__ import annotations

import pytest
from feedbot_core.models import Tenant
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_db_session_works(db_session: AsyncSession):
    """The fixture yields a working AsyncSession against a migrated DB."""
    rows = (await db_session.execute(select(Tenant))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_isolation_between_tests_part_one(db_session: AsyncSession):
    """If isolation works, the row written here is invisible to part_two."""
    db_session.add(Tenant(name="from-test-one"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_isolation_between_tests_part_two(db_session: AsyncSession):
    rows = (await db_session.execute(select(Tenant))).scalars().all()
    assert rows == [], "previous test's tenant leaked — transactional rollback is broken"


@pytest.mark.asyncio
async def test_healthz(client: AsyncClient):
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
