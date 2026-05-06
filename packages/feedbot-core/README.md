# feedbot-core

Shared domain primitives for the Feedbot ecosystem.

- `models.py` — SQLAlchemy declaratives (Tenant, User, Project, ApiKey, ChatLink, Feedback, ...).
- `repos.py` — small, async, session-aware repository functions. No HTTP. No framework.
- `ids.py` — `FB-XXXXXX` and `fbk_live_...` generators.
- `security.py` — Argon2 hashing helpers.
- `db.py` — `make_engine` / `make_sessionmaker` / `session_scope` helpers.
- `settings.py` — pydantic-settings root for `DATABASE_URL`, `FEEDBOT_SECRET_KEY`, etc.

This package never imports FastAPI or python-telegram-bot. It is the dependency floor.
