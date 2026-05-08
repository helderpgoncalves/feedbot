# syntax=docker/dockerfile:1.7

# ── Build stage ──────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.15.0 --activate

# Install with cache mount; copy lockfile + manifest first for layer reuse.
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
	pnpm install --frozen-lockfile

COPY . .

# Optional: bake the commit SHA into the build for traceability.
ARG BUILD_SHA=""
ENV VITE_BUILD_SHA=${BUILD_SHA}

RUN pnpm build

# ── Runtime stage ────────────────────────────────────────────────────────────
# Plain nginx serving the SPA. Reverse-proxy responsibilities (routing
# /api/* and /mcp/* to feedbot-api) live in the *external* Caddy at
# ../caddy/ — see the root docker-compose.yml. This image is now a
# pure static-asset server, deployable behind anything (Caddy, Traefik,
# Coolify, Cloudflare Pages, etc.).
FROM nginx:alpine AS runner

# Replace the default site with ours. Static config — no envsubst on
# this file because nginx doesn't need anything templated.
COPY nginx.conf.template /etc/nginx/conf.d/default.conf

# Built SPA bundle.
COPY --from=builder /app/dist /usr/share/nginx/html

# Runtime config templating: regenerates /config.json from env vars
# every time the container starts. Self-hosters edit env in their
# orchestrator (compose, Coolify, k8s) and `restart` — no rebuild.
COPY entrypoint.sh /docker-entrypoint.d/30-feedbot-config.sh
RUN chmod +x /docker-entrypoint.d/30-feedbot-config.sh

# Default values rendered into config.json when the container boots.
# All overridable at runtime; the orchestrator passes real values.
ENV FEEDBOT_PRODUCT_NAME="Feedbot" \
    FEEDBOT_PUBLIC_URL="" \
    FEEDBOT_MCP_PUBLIC_URL="" \
    FEEDBOT_TELEGRAM_BOT_USERNAME="" \
    FEEDBOT_ALLOW_SIGNUP="false" \
    FEEDBOT_BILLING_ENABLED="false" \
    FEEDBOT_DEPLOYMENT="self-host" \
    FEEDBOT_BUILD_SHA=""

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
	CMD wget -qO- http://127.0.0.1/config.json >/dev/null || exit 1
