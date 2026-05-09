# Multi-stage build for the marketing site at feedbot.dev.
#
# Stage 1: build the Astro+Starlight site to dist/.
# Stage 2: serve dist/ via nginx:alpine on port 80. The edge container
#          in docker-compose.cloud.yml proxies feedbot.dev (Host-routed)
#          to this service.
#
# Why nginx (not caddy): we keep the same web server everywhere in the
# stack so operators only learn one config language. The edge proxy is
# nginx, the SPA container is nginx, and so is this. Single source of
# operational knowledge.

FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.15.0 --activate

# Copy lockfile first so node_modules layer caches between content
# changes. Astro pulls a lot of deps; this matters.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --prod=false

# Now the actual content.
COPY . .
RUN pnpm build


FROM nginx:alpine AS runner

# Standard static-site nginx config. Pretty-URL fallback so Astro
# routes that build to nested index.html files keep working
# (Starlight's `editLink` and `pagination` rely on this).
RUN cat > /etc/nginx/conf.d/default.conf <<'NGINX'
server {
    listen 80 default_server;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    gzip on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml application/xml;
    gzip_min_length 1024;

    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Long-cache fingerprinted Astro assets, no-cache for HTML.
    # Astro's _astro/ folder contains the hashed bundles.
    location /_astro/ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location ~ \.html$ {
        add_header Cache-Control "no-cache, must-revalidate";
    }

    # Pretty URLs: /docs/foo  >>>  /docs/foo/index.html
    location / {
        try_files $uri $uri/ $uri.html $uri/index.html =404;
    }
}
NGINX

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
