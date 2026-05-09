# Static host for get.feedbot.dev — serves install.sh as plain text to
# curl/wget, and a friendly explainer page to browsers.
#
# The build.sh script copies install.sh + writes an index.html into
# dist/. We run it at image build time and serve dist/ via nginx.
#
# The clever bit is the User-Agent rewrite: a request to / from
# `curl | sh` should return the SHELL SCRIPT, not the HTML. nginx maps
# the User-Agent and rewrites internally without an HTTP redirect — so
# pipelines never break on a 302.

FROM alpine:3 AS builder
WORKDIR /build

# build.sh expects the repo to be reachable at ../.. — we copy what it
# needs (install.sh + the script itself) into a faux layout. Keeps the
# script unchanged and reusable for the Coolify static path.
COPY install.sh /repo/install.sh
COPY apps/installer-host/ /repo/apps/installer-host/

RUN sh /repo/apps/installer-host/build.sh


FROM nginx:alpine AS runner

RUN cat > /etc/nginx/conf.d/default.conf <<'NGINX'
# Browsers see index.html with copy-paste instructions; curl/wget see
# the raw shell script. The map runs against the User-Agent header.
map $http_user_agent $is_shell_client {
    default      0;
    "~*curl"     1;
    "~*wget"     1;
    "~*fetch"    1;
}

server {
    listen 80 default_server;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Direct hits to /install.sh always return the script as text/plain,
    # regardless of client.
    location = /install.sh {
        types { } default_type text/plain;
        try_files /install.sh =404;
    }

    # Pipe-able root: `curl https://get.feedbot.dev | sh` lands here.
    # Internal rewrite (no 302) so curl follows it as the same request.
    location = / {
        if ($is_shell_client) {
            rewrite ^ /install.sh last;
        }
        try_files /index.html =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
NGINX

COPY --from=builder /repo/apps/installer-host/dist /usr/share/nginx/html

EXPOSE 80
