<div align="center">

# Feedbot

**Turn community chat into a structured product backlog — and let Claude Code resolve it.**

[![License: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![MCP-compatible](https://img.shields.io/badge/MCP-compatible-emerald.svg)](https://modelcontextprotocol.io)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-orange.svg)](CONTRIBUTING.md)

</div>

---

Drop the Feedbot bot into your **Telegram** (or, soon, **WhatsApp**) groups. Users post bugs, ideas, and feature requests in plain language. Feedbot structures them, your team triages from the **web dashboard**, and **Claude Code** resolves them through the bundled **MCP server** — closing the loop with the original reporter automatically.

```
       ┌──────────────┐                       ┌────────────────┐
       │  Telegram /  │   bot creates rows    │   Feedbot API  │
       │  WhatsApp    │ ───────────────────►  │  (Postgres,    │
       │  groups      │ ◄─────── reply ────── │   FastAPI)     │
       └──────────────┘                       └───────┬────────┘
                                                      │
       ┌──────────────┐    Bearer fbk_*               │
       │  Claude Code │ ◄──────────────────────────►  │
       │   + MCP      │       HTTP                    │
       └──────────────┘                       ┌───────┴────────┐
                                              │  Web Dashboard │
                                              │   (Jinja+HTMX) │
                                              └────────────────┘
```

---

## Why this exists

Product feedback in Telegram groups is chaos: ideas drown in scroll, bug reports lack repro steps, screenshots vanish, and reporters never know if their suggestion was even read.

Feedbot fixes this with three moves:

1. **Capture.** A bot in your chat turns free-form messages into typed, severity-tagged rows.
2. **Triage.** A clean web dashboard — one project per chat group — gives you the inbox.
3. **Resolve.** A first-class MCP server lets Claude Code read tickets, write the fix, and mark them `done` — at which point the reporter is automatically notified back in chat.

You stay in your editor. Reporters stay in their group. Nothing falls through.

---

## ✨ Highlights

- **One bot, N projects.** A single Telegram bot serves every project you own. Each chat is bound to exactly one project; routing is decided server-side from `chat_id`. The same bot, the same brand, isolated inboxes.
- **Frictionless onboarding.** From the dashboard you click *"Generate Telegram invite"* → choose a group in Telegram → tap *Start*. The bot confirms the link in chat. No tokens to type, no commands to remember.
- **First-class MCP.** Wire your Claude Code workspace to the project with one CLI command. Triage, fix, document, reply to users — all from your editor.
- **Multi-tenant by design.** Tenants → projects → API keys, with `UNIQUE(platform, chat_id)` so a chat can never bleed into another project.
- **Boring tech, on purpose.** FastAPI, SQLAlchemy 2 async, Postgres, Alembic, Jinja + HTMX + Tailwind. Two `docker compose` commands and you're up.
- **Argon2-hashed API keys**, prefix-only display, scoped (`read|write|admin`), revocable. No plaintext keys at rest.

---

## Quickstart (Docker, 5 minutes)

```bash
git clone https://github.com/helderpgoncalves/feedbot.git
cd feedbot
cp .env.example .env

# Generate strong dev secrets and paste them into .env
python -c "import secrets; print('FEEDBOT_SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import secrets; print('FEEDBOT_BOT_TOKEN='  + secrets.token_urlsafe(32))"

docker compose up --build -d db api

# Create a project + API key without clicking through the dashboard
docker compose exec api python scripts/seed.py \
  --email you@example.com --slug demo --name "Demo Project"
```

Open <http://localhost:8000> → sign in (magic link prints to `docker compose logs api`). The full happy-path walkthrough — including Telegram and the MCP server — is in **[`docs/E2E.md`](docs/E2E.md)**.

---

## Wire up Claude Code

Reference: <https://code.claude.com/docs/en/mcp>.

```bash
pip install -e packages/feedbot-mcp

claude mcp add feedbot \
  --transport stdio \
  --env FEEDBOT_API_URL=http://localhost:8000 \
  --env FEEDBOT_API_KEY=fbk_live_... \
  -- feedbot-mcp
```

Or commit a project-scoped `.mcp.json`:

```json
{
  "mcpServers": {
    "feedbot": {
      "command": "feedbot-mcp",
      "args": [],
      "env": {
        "FEEDBOT_API_URL": "http://localhost:8000",
        "FEEDBOT_API_KEY": "fbk_live_..."
      }
    }
  }
}
```

> **All flags must come before the server name**, then `--`, then the command. This is per the [official docs](https://code.claude.com/docs/en/mcp).

In Claude Code: *"What new bugs do we have?"* → done.

---

## What's in this repo

A **monorepo**. One install, four publishable packages.

```
feedbot/
├── packages/
│   ├── feedbot-core/   # SQLAlchemy models, repos, IDs, security
│   ├── feedbot-api/    # FastAPI + Jinja+HTMX dashboard
│   ├── feedbot-bot/    # Telegram (and later WhatsApp) adapters
│   └── feedbot-mcp/    # MCP server — thin HTTP client for Claude Code
├── alembic/            # Migrations (single shared schema)
├── docker-compose.yml  # db + api + bot, one command up
├── scripts/seed.py     # CLI: create project + key without clicking
└── docs/               # ARCHITECTURE, DEPLOYMENT, E2E
```

| Package | What it does | Runs where |
|---|---|---|
| `feedbot-core` | Domain models, repositories, ID generation, Argon2 hashing. No I/O policy. | Imported by api/bot |
| `feedbot-api` | REST API (`/v1/*`), magic-link auth, web dashboard. **Source of truth.** | Server |
| `feedbot-bot` | Global Telegram bot. Resolves project from `chat_id`. | Server |
| `feedbot-mcp` | MCP stdio server. ~150 LOC. Talks to the API over HTTPS. | Developer's machine |

---

## How multi-project routing works

```
                          ┌─────────────────────────────────┐
                          │  feedbot-api                    │
                          │                                 │
   /start link_<token> ──►│  /v1/internal/redeem-link       │──► chat_links: (telegram, -100…) → project A
                          │                                 │
   message in group A  ──►│  /v1/internal/ingest            │──► looks up chat_links → project A → new feedback
                          │                                 │
   message in group B  ──►│  /v1/internal/ingest            │──► looks up chat_links → project B → new feedback
                          └─────────────────────────────────┘
```

- The dashboard issues a single-use, 15-minute deep-link token.
- Telegram's `?startgroup=link_<token>` brings the user (with the bot) into a group of their choice.
- The bot calls `/v1/internal/redeem-link` with `(chat_id, token)` → server records the binding.
- Every subsequent message in that chat is ingested against that project.
- `UNIQUE(platform, chat_id)` makes it physically impossible for a chat to belong to two projects.
- Bot ↔ API uses a **separate** server-side secret (`FEEDBOT_BOT_TOKEN`) that is never exposed to users or browsers — distinct from the user-facing `fbk_*` API keys.

---

## The MCP tools

| Tool | What Claude does with it |
|---|---|
| `list_feedbacks` | *"What's in the new bug pile?"* |
| `get_feedback` | *"Pull up FB-A3F2."* |
| `update_status` | *"Mark FB-A3F2 done — fixed in PR #91."* |
| `add_note` | *"Note on FB-B7C1: needs design review."* |
| `reply_to_user` | *"Ask the reporter of FB-A3F2 for their iOS version."* |
| `search_feedbacks` | *"Have we seen this export crash before?"* |
| `get_stats` | *"How's the pipeline?"* |

---

## Roadmap

- **M1 (now)** — Telegram, dashboard, MCP, multi-project, magic-link auth, deep-link onboarding.
- **M1.5** — `/mcp` HTTP endpoint on the API (skip the stdio package entirely; use `claude mcp add --transport http`).
- **M2** — WhatsApp via Baileys sidecar (self-hosted by user, points at your API).
- **M3** — LLM classification (type, severity, tags) on inbound messages.
- **M4** — Outbound notification worker — when status flips to `done`, DM the reporter.
- **M5** — Multi-tenant hosted WhatsApp (managed sessions).

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for production notes.

---

## Security

- API keys: Argon2id-hashed, only the prefix stored in the clear.
- Bot ↔ API authenticated with a server-side shared secret (`FEEDBOT_BOT_TOKEN`), constant-time comparison.
- Magic-link tokens: hashed at rest, single-use, 15-minute TTL.
- Chat-link tokens: hashed-of-record, single-use, 15-minute TTL, marked `used_at` atomically.
- `UNIQUE(platform, chat_id)` enforces one-chat-one-project at the DB layer.
- No third-party JS in the dashboard except Tailwind CDN + HTMX (auditable in `templates/base.html`).

Found something? Read [`SECURITY.md`](SECURITY.md) — please don't open public issues for vulnerabilities.

---

## Contributing

We genuinely want PRs. The codebase is intentionally small and readable — each package is a few hundred lines.

- 📖 [`CONTRIBUTING.md`](CONTRIBUTING.md) — local setup and conventions
- 🧱 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — why things are shaped this way
- 🧪 [`docs/E2E.md`](docs/E2E.md) — verify everything works locally before opening a PR
- 💬 [Discussions](https://github.com/helderpgoncalves/feedbot/discussions) — design questions, proposals
- 🐛 [Issues](https://github.com/helderpgoncalves/feedbot/issues) — bugs and small features (use the templates)

```bash
# Quick dev setup
docker compose up db -d
for p in packages/*; do pip install -e "$p"; done
alembic upgrade head
uvicorn feedbot_api.app:app --reload
```

---

## License

MIT. See [`LICENSE`](LICENSE).
