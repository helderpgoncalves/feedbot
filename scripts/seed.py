"""Seed a project + API key — non-interactively.

Usage (inside the api container, or with DATABASE_URL pointing at the live DB):

    python scripts/seed.py --email me@example.com --slug demo --name "Demo Project"

Behaviour:
- If the database is empty, this script bootstraps the tenant + the **owner** user.
- If the email already exists, it uses that user's tenant.
- If the email does not exist but the database is non-empty, it refuses (you must
  invite that email through the dashboard — the closed-loop login model does not
  permit silent user creation).
- It then ensures a project with the given slug exists and issues a fresh API key.

The full key is printed once to stdout — copy it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from feedbot_core.db import make_engine, make_sessionmaker, session_scope
from feedbot_core.repos import (
    bootstrap_owner,
    count_users,
    create_project,
    get_project_by_slug,
    get_user_by_email,
    issue_api_key,
)


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
        user = await get_user_by_email(session, args.email.lower().strip())
        if user is None:
            if await count_users(session) == 0:
                user = await bootstrap_owner(session, args.email, tenant_name=args.email.split("@")[0])
            else:
                print(
                    f"refusing: user {args.email} does not exist and the database is not empty.\n"
                    "Invite them through /app/team in the dashboard instead.",
                    file=sys.stderr,
                )
                return 1

        project = await get_project_by_slug(session, user.tenant_id, args.slug)
        if project is None:
            project = await create_project(session, user.tenant_id, args.slug, args.name)
        _, full_key = await issue_api_key(session, project.id, label=args.label)

    print("─" * 60)
    print(f"  email     {args.email}")
    print(f"  role      {user.role}")
    print(f"  tenant    {user.tenant_id}")
    print(f"  project   {project.slug}  (id={project.id})")
    print(f"  api key   {full_key}")
    print("─" * 60)
    print("Add the api key to your Claude Code .mcp.json under FEEDBOT_API_KEY.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
