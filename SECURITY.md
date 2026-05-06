# Security policy

## Reporting a vulnerability

**Please do not open public issues for security vulnerabilities.**

Email **helderpgoncalves [at] users.noreply.github.com** (or open a [private security advisory](https://github.com/helderpgoncalves/feedbot/security/advisories/new)) with:

- A description of the issue and its impact
- Steps to reproduce (or a proof-of-concept)
- The commit / version affected

You'll get an acknowledgement within 72 hours and a status update within 7 days. Coordinated disclosure preferred — typical embargo 30–90 days depending on severity.

## Supported versions

Feedbot is pre-1.0. Only the `main` branch receives security fixes. Once we tag 1.0 we'll publish a support matrix here.

## Scope

In scope:
- The API (`feedbot-api`), bot (`feedbot-bot`), MCP server (`feedbot-mcp`), and core (`feedbot-core`) packages.
- Default Docker compose deployment.

Out of scope:
- Third-party libraries (report upstream).
- Self-host misconfiguration (e.g., running with `FEEDBOT_SECRET_KEY=dev-secret` in production).
- Rate-limiting / DoS — known gap, planned (issue welcome).

## Threat model (at a glance)

| Asset | How it's protected |
|---|---|
| User-facing API keys (`fbk_*`) | Argon2id hash, only `fbk_<env>_<8>` prefix stored visible. Constant-time prefix lookup + verify. |
| Bot ↔ API channel | Separate server-side `FEEDBOT_BOT_TOKEN`, `hmac.compare_digest`, never sent to clients. |
| Magic-link tokens | Argon2 hashed, 15-min TTL, single-use, scoped to email. |
| Chat-link tokens | 32-byte urlsafe, 15-min TTL, single-use, atomic `used_at`. |
| Cross-project isolation | `UNIQUE(platform, chat_id)` + `project_id` filter on every query. |
| Session cookies | `itsdangerous`-signed, `secret_key` from env, HTTPS-only when `FEEDBOT_BASE_URL` is `https`. |

## Hardening checklist for self-hosters

Before exposing Feedbot to the internet:

- [ ] Generate a strong `FEEDBOT_SECRET_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
- [ ] Generate a strong `FEEDBOT_BOT_TOKEN` (same recipe).
- [ ] Front the API with TLS (Caddy / Traefik / nginx).
- [ ] Set `FEEDBOT_BASE_URL` to your public `https://...` URL.
- [ ] Configure real SMTP (`EMAIL_BACKEND=smtp`) so magic links don't only print to logs.
- [ ] Run `docker compose` with a dedicated non-root user.
- [ ] Schedule `pg_dump` backups.
