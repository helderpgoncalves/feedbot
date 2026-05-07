# Feedbot web (`app.feedbot.dev`)

The single React/Vite SPA that powers both Cloud (`app.feedbot.dev`) and self-host. Same image, runtime config injected by Caddy on each request — self-hosters change env vars and `restart`, never rebuild.

## Stack

- **Vite 6** + **React 19** + **TypeScript strict**
- **TanStack Router** (file-based, type-safe) + **TanStack Query**
- **Tailwind v4** + **shadcn/ui** (new-york preset, neutral palette)
- **react-hook-form** + **Zod** for forms
- **openapi-fetch** + **openapi-typescript** for a typed API client (zero schema duplication)
- **Caddy** for production: SPA serve + same-origin `/api/*` proxy + runtime `/config.json`

## Local dev

The dev server proxies `/api/*` to `feedbot-api` running on `:8000` so cookies stay same-origin in dev too.

```bash
# Bring up the API + Postgres in another shell
docker compose up -d db api

# Then in this folder
pnpm install
pnpm gen:api          # pulls openapi.json from FEEDBOT_API_OPENAPI_URL (defaults to localhost:8000)
pnpm dev              # http://localhost:3000
```

Override the proxy target with `VITE_API_PROXY=http://10.0.0.5:8000 pnpm dev`.

## Generating API types

We keep a typed client by reading the live OpenAPI from `feedbot-api`:

```bash
# default
pnpm gen:api

# against a different API (e.g. cloud staging)
FEEDBOT_API_OPENAPI_URL=https://api.staging.feedbot.dev/openapi.json pnpm gen:api
```

`src/types/api.ts` and `src/routeTree.gen.ts` are committed so CI doesn't need a running API to build. Re-run `gen:api` whenever the API surface changes.

## Production build

```bash
pnpm build            # → dist/
pnpm preview          # serve dist locally on :4173
```

## Runtime configuration

The SPA fetches `/config.json` on boot. In production, Caddy renders that file from environment variables — change them in `docker-compose.yml` and `docker compose restart web` and the new values are live, **no rebuild**.

| Env var | Default | Notes |
|---|---|---|
| `FEEDBOT_API_UPSTREAM` | `http://api:8000` | Where Caddy proxies `/api/*`, `/login`, `/setup`, `/mcp/`. |
| `FEEDBOT_PRODUCT_NAME` | `Feedbot` | Shown in the UI header. |
| `FEEDBOT_PUBLIC_URL` | `""` | Public URL of this web app — used in emails / share links. |
| `FEEDBOT_TELEGRAM_BOT_USERNAME` | `""` | Powers the "Connect Telegram" deep link. Without it, that button hides. |
| `FEEDBOT_ALLOW_SIGNUP` | `false` | Cloud sets `true`; self-host stays `false` (invite-only). |
| `FEEDBOT_DEPLOYMENT` | `self-host` | `cloud` shows plan/billing UI; `self-host` hides it. |
| `FEEDBOT_BUILD_SHA` | `""` | Optional commit SHA for footer traceability. |

## Deploy on Coolify

1. **New resource → Application** → repo `helderpgoncalves/feedbot`, branch `main`, **Build Pack: Dockerfile**, **Base Directory: `/apps/web`**, **Dockerfile location: `/apps/web/Dockerfile`**.
2. **Domain**: `app.feedbot.dev`. Coolify provisions Let's Encrypt automatically.
3. **Port**: `80`.
4. **Environment**: set `FEEDBOT_API_UPSTREAM=http://feedbot-api:8000` (or the public URL of your API), and the variables in the table above.
5. Push to `main` → auto-build + deploy.
