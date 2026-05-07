# Feedbot site (feedbot.dev)

Astro Starlight project with the [`starlight-theme-black`](https://github.com/adrian-ub/starlight-theme-black) theme. Marketing landing + full docs.

## Local dev

```bash
pnpm install
pnpm dev          # http://localhost:4321
```

## Build

```bash
pnpm build        # → dist/
pnpm preview      # serve dist locally
```

## Content

- **Marketing pages** live as `splash`-template MDX in `src/content/docs/` — `index.mdx`, `self-host.mdx`, `cloud.mdx`, `pricing.mdx`.
- **Authored docs** are plain MDX/MD in `src/content/docs/` — quickstart, MCP tools, LLM providers, HTTP API, cloud overview.
- **Symlinked docs** point back to the canonical Markdown in the repo root and `docs/` — `ARCHITECTURE.md`, `E2E.md`, `DEPLOY-COOLIFY.md`, `DEPLOYMENT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`. Edit the source; the site rebuilds.

The sidebar is configured in `astro.config.mjs`.

## Deploy on Coolify

1. **New resource** → **Application** → repository: `helderpgoncalves/feedbot`, branch `main`, **Build pack: Dockerfile**, **Base directory: `/site`**, **Dockerfile location: `/site/Dockerfile`**.
2. **Domain**: `feedbot.dev` (and `www.feedbot.dev` if desired). Coolify provisions Let's Encrypt automatically.
3. **Port**: `80` (Caddy listens on 80; Coolify proxies TLS in front).
4. Push to `main` → auto-build + deploy.

DNS:
- `feedbot.dev` → A record → Coolify host IP
- `www.feedbot.dev` → CNAME → `feedbot.dev`

## Other hosts

The output is plain static HTML in `dist/` — works on Cloudflare Pages, Vercel, Netlify, GitHub Pages, anywhere.
