# Changelog

All notable changes to this project will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **First-run setup (`/setup`)** — Coolify-style onboarding when the database is empty. Creates the owner account and sends them the first magic link.
- **Roles**: `owner`, `admin`, `member`. Members only see projects they were explicitly added to.
- **Invites** with 7-day single-use tokens, sent via email by the team admin.
- **Per-project membership** — admins assign members to projects from the project page.
- **Ownership transfer** — owners can hand the role to another admin.
- **Email backends** — `console` for dev, `smtp` (TLS / STARTTLS) for production.
- **Security headers** middleware — HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy.
- **Rate limiting** via `slowapi` on `/login`, `/setup`, `/invites/*`, with sane defaults elsewhere.
- **Coolify deployment guide** (`docs/DEPLOY-COOLIFY.md`) with managed-Postgres + SMTP walkthrough.
- Multi-project routing: one Telegram bot serves N projects, project resolved from `chat_id` via `chat_links`.
- Deep-link onboarding (`t.me/<bot>?startgroup=link_<token>`) — single-use 15-min tokens, atomic redeem.
- Internal endpoints `/v1/internal/{ingest,redeem-link}` authenticated with server-side `FEEDBOT_BOT_TOKEN`.
- Dashboard: connect / disconnect chats per project, with deep-link button.
- `scripts/seed.py` — non-interactive project + key creation.
- Architecture, deployment, and E2E docs.

### Changed
- **Login is closed**: `/login` no longer auto-creates accounts. Same response whether the email exists or not (no enumeration).
- Magic-link refused when `EMAIL_BACKEND=console` and `FEEDBOT_BASE_URL` is `https://` — prevents silently broken production deployments.
- Session cookies are now `https_only` when serving over HTTPS, `same_site=lax`.

## [0.1.0] - planned

Initial public release: capture (Telegram), triage (dashboard), resolve (MCP server).
