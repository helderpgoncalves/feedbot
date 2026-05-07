---
title: Contributing
description: Local setup, conventions, and how to open a PR against Feedbot.
---

# Contributing to Feedbot

Thanks for being here. Feedbot is intentionally small — under a few hundred lines per package — so reading the code first is the fastest way in.

## Local setup

```bash
git clone https://github.com/helderpgoncalves/feedbot.git
cd feedbot
cp .env.example .env

# Bring up Postgres
docker compose up db -d

# Install the workspace (feedbot-core first; the others depend on it)
pip install -e packages/feedbot-core \
            -e packages/feedbot-api \
            -e packages/feedbot-bot \
            -e packages/feedbot-mcp

# Run migrations
alembic upgrade head

# Run the API with autoreload
uvicorn feedbot_api.app:app --reload
```

The dashboard is at `http://localhost:8000`. Magic links print to the API console.

## Project layout

- `packages/feedbot-core` — pure domain (no FastAPI, no Telegram). Add new fields here.
- `packages/feedbot-api` — HTTP, auth, dashboard.
- `packages/feedbot-bot` — messaging adapters.
- `packages/feedbot-mcp` — MCP server. Should stay tiny and dependency-light.

## Conventions

- Type hints everywhere; `ruff` for lint, default config in root `pyproject.toml`.
- New tables → SQLAlchemy model in `feedbot_core/models.py` **and** an Alembic revision.
- New API endpoint → router in `feedbot_api/routers/`, schema in `schemas.py`, optional MCP tool in `feedbot_mcp/server.py`.
- Tests go in `packages/<pkg>/tests/`. Async via `pytest-asyncio`.

## Pull requests

- One concern per PR. Small > grand.
- If it touches the API surface, update the README's MCP-tools table.
- If it changes the schema, your PR includes the migration.

## Code of conduct

Be kind. We're shipping a tool to make collaboration easier — start there.
