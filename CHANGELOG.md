# Changelog

All notable changes to this project will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Multi-project routing: one Telegram bot serves N projects, project resolved from `chat_id` via `chat_links`.
- Deep-link onboarding (`t.me/<bot>?startgroup=link_<token>`) — single-use 15-min tokens, atomic redeem.
- Internal endpoints `/v1/internal/{ingest,redeem-link}` authenticated with server-side `FEEDBOT_BOT_TOKEN`.
- Dashboard: connect / disconnect chats per project, with deep-link button.
- `scripts/seed.py` — non-interactive project + key creation.
- Architecture, deployment, and E2E docs.

## [0.1.0] - planned

Initial public release: capture (Telegram), triage (dashboard), resolve (MCP server).
