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
FROM caddy:2-alpine AS runner
WORKDIR /srv

COPY --from=builder /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile

# Default upstream for self-host docker-compose; overridable at runtime.
ENV FEEDBOT_API_UPSTREAM="http://api:8000" \
	FEEDBOT_PRODUCT_NAME="Feedbot" \
	FEEDBOT_PUBLIC_URL="" \
	FEEDBOT_MCP_PUBLIC_URL="" \
	FEEDBOT_TELEGRAM_BOT_USERNAME="" \
	FEEDBOT_ALLOW_SIGNUP="false" \
	FEEDBOT_DEPLOYMENT="self-host" \
	FEEDBOT_BUILD_SHA=""

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
	CMD wget -qO- http://127.0.0.1/config.json >/dev/null || exit 1

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
