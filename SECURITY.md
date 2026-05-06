# Security policy

## Reporting a vulnerability

**Please do not open public issues for security vulnerabilities.**

Open a [private security advisory](https://github.com/helderpgoncalves/feedbot/security/advisories/new) with:

- A description of the issue and its impact
- Steps to reproduce (or a proof-of-concept)
- The commit / version affected

You'll get an acknowledgement within 72 hours and a status update within 7 days. Coordinated disclosure preferred — typical embargo 30–90 days depending on severity.

## Supported versions

Feedbot is pre-1.0. Only the `main` branch receives security fixes. Once we tag 1.0 we'll publish a support matrix here.

## Scope

In scope:
- The API (`feedbot-api`), bot (`feedbot-bot`), MCP server (`feedbot-mcp`), and core (`feedbot-core`) packages.
- Default Docker compose deployment and Coolify deployment guide (`docs/DEPLOY-COOLIFY.md`).

Out of scope:
- Third-party libraries (report upstream).
- Self-host misconfiguration (e.g., running with `FEEDBOT_SECRET_KEY=dev-secret` in production).

## Threat model

### Identity & access

| Asset | How it's protected |
|---|---|
| **First-run setup** | `/setup` is only reachable while `users` is empty. Once the owner is created the route returns 410. The bootstrap middleware redirects every other route to `/setup` until then, preventing accidental empty-state exposure. |
| **Login** | Magic-link only. No passwords. **No auto-signup** — `/login` returns the same generic response whether the email exists or not (prevents enumeration). Users only exist after explicit invitation by an admin (or via the bootstrap setup). |
| **Magic-link tokens** | Argon2id hashed, 15-min TTL, single-use, scoped to email. Five-link cap per email enforced by query limit. |
| **Invite tokens** | 32-byte urlsafe, 7-day TTL, single-use, atomic `used_at`. Sent only via email. |
| **Sessions** | Signed (`itsdangerous`) cookie. `https_only=True` when `FEEDBOT_BASE_URL` is `https://`. `same_site=lax`. |
| **Roles** | Three: `owner` (bootstrap, untouchable except via owner-initiated transfer), `admin` (manage tenant), `member` (sees only assigned projects). Mutating ops on a project require `is_admin`. |

### API surface

| Asset | How it's protected |
|---|---|
| User-facing API keys (`fbk_live_*`) | Argon2id hash, only `fbk_<env>_<8>` prefix stored visible. Constant-time prefix lookup + verify. Scoped (`read|write|admin`), revocable. |
| Bot ↔ API channel | Separate server-side `FEEDBOT_BOT_TOKEN`, `hmac.compare_digest`, never sent to clients. Returns 503 if unset (fail-closed). |
| `/v1/internal/*` | All routes require the bot token. Project resolved server-side from `chat_id`; clients can never hint at a project. |
| Cross-project isolation | `UNIQUE(platform, chat_id)`, `project_id` filter on every query, `tenant_id` filter on every cross-project query. Members see only `project_members`-joined projects. |
| Chat-link tokens | 32-byte urlsafe, 15-min TTL, single-use, `used_chat_id` recorded for forensics. |

### Transport & headers

| Header | Policy |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (only when `FEEDBOT_BASE_URL` is `https://`). |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' https://cdn.tailwindcss.com https://unpkg.com 'unsafe-inline'; style-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'` |

### Rate limiting

`slowapi` with in-memory storage:
- `/login`: 5 / 15 min / IP
- `/login/verify`: 10 / 15 min / IP
- `/setup`: 3 / 15 min / IP
- `/invites/{token}` POST: 5 / 15 min / IP
- All other endpoints: 200/min/IP (default)

For multi-replica deployments swap `slowapi`'s in-memory storage for Redis (one-line change in `feedbot_api/rate_limit.py`).

### Production fail-safes

- `EMAIL_BACKEND=console` + `FEEDBOT_BASE_URL=https://...` → `/login` returns `503 Email delivery not configured`. Prevents silently broken auth in production.
- `FEEDBOT_BOT_TOKEN` unset → `/v1/internal/*` returns `503`. Prevents a misconfigured bot from accepting unsigned ingest.

## Hardening checklist for self-hosters

Before exposing Feedbot to the internet:

- [ ] Generate `FEEDBOT_SECRET_KEY` ≥48 chars: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- [ ] Generate `FEEDBOT_BOT_TOKEN` ≥32 chars: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- [ ] Front the API with TLS (Caddy / Traefik / Coolify).
- [ ] Set `FEEDBOT_BASE_URL=https://...` so cookies, HSTS, and the magic-link refusal kick in.
- [ ] Configure SMTP (`EMAIL_BACKEND=smtp` + `SMTP_*`) before inviting anyone.
- [ ] Run `docker compose` with a non-root user (Coolify does this by default).
- [ ] Schedule Postgres backups (Coolify-managed db has a toggle).
- [ ] Keep dependabot PRs reviewed and merged.
