"""Seed a tenant, user, project and one API key — non-interactively.

Usage (inside the api container or with DATABASE_URL pointing at the local DB):

    python scripts/seed.py --email me@example.com --slug demo --name "Demo Project"

Prints the freshly issued API key to stdout. Idempotent on (email, slug):
re-running with the same args will reuse the tenant/project and just issue
another key (so you always get a usable key out of it).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from feedbot_core.db import make_engine, make_sessionmaker, session_scope
from feedbot_core.models import Project, User
from feedbot_core.repos import create_project, get_or_create_user, issue_api_key


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--label", default="seed")
    args = parser.parse_args()

    engine = make_engine()
    sm = make_sessionmaker(engine)

    async with session_scope(sm) as session:
        user = await get_or_create_user(session, args.email)
        existing = (
            await session.execute(
                select(Project).where(Project.tenant_id == user.tenant_id, Project.slug == args.slug)
            )
        ).scalar_one_or_none()
        project = existing or await create_project(session, user.tenant_id, args.slug, args.name)
        _, full_key = await issue_api_key(session, project.id, label=args.label)

    print("─" * 60)
    print(f"  email     {args.email}")
    print(f"  tenant    {user.tenant_id}")
    print(f"  project   {project.slug}  (id={project.id})")
    print(f"  api key   {full_key}")
    print("─" * 60)
    print("Add to your Claude Code .mcp.json under FEEDBOT_API_KEY.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
