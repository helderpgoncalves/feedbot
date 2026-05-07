"""Shared pytest fixtures for feedbot-api integration tests.

Strategy
--------

- One real Postgres test database per session. Spin-up:

    1. Ensure the database referenced by ``FEEDBOT_TEST_DATABASE_URL`` exists
       (the maintenance DSN ``FEEDBOT_TEST_DATABASE_ADMIN_URL`` is used to
       create it if missing — defaults to ``postgres`` on the same host).
    2. Drop+recreate the public schema. This is faster than dropping the DB
       and avoids the complexity of disconnecting active sessions.
    3. Run ``alembic upgrade head`` against the test DB once per session.

- Per-test isolation: the ``db_session`` fixture opens a connection, begins
  a transaction, opens a SAVEPOINT-aware ``AsyncSession`` bound to it, and
  rolls everything back at teardown. Tests can ``commit`` freely; they only
  affect their own savepoint.

- The FastAPI app's ``get_session`` dependency is overridden to yield the
  per-test session, so any HTTP request inside a test sees the same in-flight
  transaction.

Why a real Postgres rather than SQLite-in-memory: the codebase relies on
Postgres-specific features (Alembic migrations targeting Postgres column
types, ``func.now()`` server defaults, JSONB, BIGSERIAL). Testing against
SQLite would lie about what production does.

Required env (sane defaults pointing at the local docker-compose db):
    FEEDBOT_TEST_DATABASE_URL         (default: postgresql+asyncpg://postgres:postgres@localhost:5432/feedbot_test)
    FEEDBOT_TEST_DATABASE_ADMIN_URL   (default: postgresql://postgres:postgres@localhost:5432/postgres)
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# Set DATABASE_URL *before* anything imports feedbot_core.settings so the
# CoreSettings cached defaults pick up the test DB.
_DEFAULT_TEST_DSN = "postgresql+asyncpg://postgres:postgres@localhost:5432/feedbot_test"
_DEFAULT_ADMIN_DSN = "postgresql://postgres:postgres@localhost:5432/postgres"

TEST_DSN = os.environ.setdefault("FEEDBOT_TEST_DATABASE_URL", _DEFAULT_TEST_DSN)
ADMIN_DSN = os.environ.setdefault("FEEDBOT_TEST_DATABASE_ADMIN_URL", _DEFAULT_ADMIN_DSN)
os.environ["DATABASE_URL"] = TEST_DSN
# Pin the auth secrets so cookies behave deterministically.
os.environ.setdefault("FEEDBOT_SECRET_KEY", "test-secret-key-do-not-ship")
os.environ.setdefault("FEEDBOT_BOT_TOKEN", "test-bot-token")
# Avoid a real SMTP attempt in tests.
os.environ.setdefault("EMAIL_BACKEND", "console")

from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from alembic.config import Config as AlembicConfig
from feedbot_core import auth_sessions
from feedbot_core.models import Project, Role, Tenant, User
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command as alembic_command

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


# ─── Session-scoped DB setup ───────────────────────────────────────────────


def _ensure_test_db_exists() -> None:
    """Create the test database if it doesn't yet exist."""
    parsed = urlsplit(TEST_DSN.replace("+asyncpg", ""))
    target_db = parsed.path.lstrip("/")
    if not target_db:
        raise RuntimeError(f"FEEDBOT_TEST_DATABASE_URL has no database name: {TEST_DSN}")

    admin = create_sync_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target_db}
        ).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target_db}"'))
    admin.dispose()


def _wipe_schema() -> None:
    """Drop + recreate ``public`` so each session starts from a known empty state."""
    sync_dsn = TEST_DSN.replace("+asyncpg", "")
    engine = create_sync_engine(sync_dsn)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _run_alembic_upgrade_head() -> None:
    """Apply every Alembic migration against the test DB."""
    cfg = AlembicConfig(os.path.join(PROJECT_ROOT, "alembic.ini"))
    cfg.set_main_option(
        "script_location", os.path.join(PROJECT_ROOT, "alembic")
    )
    cfg.set_main_option("sqlalchemy.url", TEST_DSN)
    alembic_command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_test_db() -> None:
    """Create the test DB, wipe its schema, run migrations once."""
    _ensure_test_db_exists()
    _wipe_schema()
    _run_alembic_upgrade_head()


@pytest_asyncio.fixture
async def engine():
    """Per-test async engine.

    pytest-asyncio 0.23+ creates a fresh event loop per test by default.
    A session-scoped async engine therefore tries to use a closed loop on
    the second test and asyncpg raises ``Event loop is closed`` at
    teardown. Function scope is the simplest way to stay correct; the
    cost is one connection-pool setup per test (~1 ms locally).
    """
    eng = create_async_engine(TEST_DSN, future=True, poolclass=None)
    try:
        yield eng
    finally:
        await eng.dispose()


# ─── Per-test session with rollback ───────────────────────────────────────


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession bound to a transaction that is rolled back
    at teardown.

    The ``join_transaction_mode='create_savepoint'`` flag lets test code
    call ``await session.commit()`` without ending the outer transaction —
    commits become SAVEPOINT releases. Roll-back of the outer transaction
    at teardown still wipes everything.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        SessionMaker = async_sessionmaker(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
            class_=AsyncSession,
        )
        async with SessionMaker() as s:
            try:
                yield s
            finally:
                await s.close()
        await outer.rollback()


# ─── HTTP client wired to the per-test session ────────────────────────────


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """``httpx.AsyncClient`` against the FastAPI app, with ``get_session``
    overridden to yield the per-test session.

    Cookies are persisted across requests on the same client instance, so a
    test can call ``POST /v1/auth/login`` then follow up with ``GET /v1/me``
    on the same client and the session cookie carries through.
    """
    # Import inside the fixture so module-level test setup of DATABASE_URL
    # is honoured before app boot.
    from feedbot_api.app import app
    from feedbot_api.deps import get_session

    async def _override_get_session():
        # Yield the test's existing session; do NOT commit/rollback inside
        # the dependency, leave that to the test fixture's outer transaction.
        try:
            yield db_session
        except Exception:
            raise

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
    ) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


# ─── Domain factories ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def make_tenant(db_session: AsyncSession):
    """Factory: create a tenant. Returns the Tenant row (id is set)."""

    async def _make(name: str = "Acme") -> Tenant:
        t = Tenant(name=name)
        db_session.add(t)
        await db_session.flush()
        return t

    return _make


@pytest_asyncio.fixture
async def make_user(db_session: AsyncSession):
    """Factory: create a user under a tenant with a given role."""

    async def _make(*, tenant: Tenant, email: str, role: Role = Role.MEMBER) -> User:
        u = User(email=email.lower(), tenant_id=tenant.id, role=role)
        db_session.add(u)
        await db_session.flush()
        return u

    return _make


@pytest_asyncio.fixture
async def make_project(db_session: AsyncSession):
    """Factory: create a project under a tenant."""

    async def _make(*, tenant: Tenant, slug: str = "demo", name: str = "Demo") -> Project:
        p = Project(tenant_id=tenant.id, slug=slug, name=name)
        db_session.add(p)
        await db_session.flush()
        return p

    return _make


@pytest_asyncio.fixture
async def login_as(db_session: AsyncSession, client: AsyncClient):
    """Helper: create a server-side session for ``user`` and set the cookie
    on the test client. Use to authenticate a request without going through
    the magic-link flow.
    """

    async def _login(user: User) -> None:
        sess = await auth_sessions.create(db_session, user=user)
        # Flush the session row so the lookup in deps.require_user finds it.
        await db_session.flush()
        # No domain — httpx then sends the cookie on every request to
        # this client regardless of host header.
        client.cookies.set("fb_session", sess.id)

    return _login
