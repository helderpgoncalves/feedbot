"""C0 billing foundations — verify the no-op contract and a 402 path.

The contract we promised in TODO-CLOUD-V1.md C0:
    1. With FEEDBOT_BILLING_ENABLED unset/false, assert_quota is a no-op
       and the subscriptions table stays empty (self-host invariant).
    2. With FEEDBOT_BILLING_ENABLED=true and a free-plan subscription,
       crossing the project limit produces a structured 402.

These tests run inside the same per-test transaction as the rest of the
suite (see conftest.py); we mutate the env var directly because
``is_billing_enabled`` reads it on every call (no module-level cache).
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
from feedbot_core.billing import QuotaExceeded, assert_quota
from feedbot_core.models import Subscription, Tenant
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def billing_disabled() -> AsyncIterator[None]:
    """Hard-pin the env var to false for the duration of a test.

    Defensive even though the default is unset — the parent test runner
    might have set it to a truthy value via pytest-env or similar.
    """
    prev = os.environ.get("FEEDBOT_BILLING_ENABLED")
    os.environ["FEEDBOT_BILLING_ENABLED"] = "false"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("FEEDBOT_BILLING_ENABLED", None)
        else:
            os.environ["FEEDBOT_BILLING_ENABLED"] = prev


@pytest.fixture
def billing_enabled() -> AsyncIterator[None]:
    """Flip the flag on for tests that exercise the real quota path."""
    prev = os.environ.get("FEEDBOT_BILLING_ENABLED")
    os.environ["FEEDBOT_BILLING_ENABLED"] = "true"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("FEEDBOT_BILLING_ENABLED", None)
        else:
            os.environ["FEEDBOT_BILLING_ENABLED"] = prev


@pytest.mark.asyncio
async def test_billing_disabled_is_noop(
    db_session: AsyncSession,
    make_tenant,
    billing_disabled,
) -> None:
    """assert_quota is a true no-op when billing is disabled.

    Calling it many times for a tenant with no Subscription row never
    raises and never inserts anything. Self-host's load characteristic.
    """
    tenant: Tenant = await make_tenant(name="Self-Host Co")
    for _ in range(50):
        await assert_quota(db_session, tenant.id, "project")
        await assert_quota(db_session, tenant.id, "feedback")
        await assert_quota(db_session, tenant.id, "member")

    # The subscriptions table must remain empty — quota.py never writes,
    # the model stays purely declarative for self-host.
    count = await db_session.execute(
        select(func.count()).select_from(Subscription)
    )
    assert count.scalar_one() == 0


@pytest.mark.asyncio
async def test_subscriptions_table_exists_empty_in_self_host(
    db_session: AsyncSession,
) -> None:
    """The migration creates the table; self-host never inserts a row.

    A direct SELECT confirms the table is reachable (migration ran) and
    empty (no implicit insert in any startup hook). This is the
    "binary-identical-to-today" promise.
    """
    rows = await db_session.execute(select(Subscription))
    assert rows.scalars().all() == []


@pytest.mark.asyncio
async def test_quota_exceeded_when_billing_enabled(
    db_session: AsyncSession,
    make_tenant,
    make_project,
    billing_enabled,
) -> None:
    """At the free-plan project limit (1), the next call raises QuotaExceeded.

    We invoke ``assert_quota`` directly rather than going through the
    HTTP layer — the API translation to 402 is exercised in the router
    tests of phase C2 (quota_402_when_enabled). Here we just verify the
    core invariant: at limit, raises with the right kind/current/limit.
    """
    tenant: Tenant = await make_tenant(name="Cloud Co")
    sub = Subscription(tenant_id=tenant.id, plan="free", status="active")
    db_session.add(sub)
    await db_session.flush()

    # Free plan allows 1 project. Create one — quota check should still
    # pass *before* the insert.
    await assert_quota(db_session, tenant.id, "project")
    await make_project(tenant=tenant, slug="p1", name="P1")

    # At limit now (1/1). assert_quota raises before the second create.
    with pytest.raises(QuotaExceeded) as excinfo:
        await assert_quota(db_session, tenant.id, "project")

    err = excinfo.value
    assert err.kind == "project"
    assert err.current == 1
    assert err.limit == 1
