#!/bin/sh
# Feedbot web entrypoint — render /config.json from env vars before
# nginx serves it.
#
# This runs inside nginx:alpine as a docker-entrypoint.d/ hook (see
# https://hub.docker.com/_/nginx). Anything in /docker-entrypoint.d/
# is executed before nginx itself starts, in numeric prefix order.
#
# Why we don't ship a static config.json: self-host operators change
# their public URL, deployment mode, telegram username, etc. without
# rebuilding the image. Templating at boot lets the same image run on
# every machine.

set -eu

OUT=/usr/share/nginx/html/config.json

# Accept null when truly unset; quote everything else as JSON string.
json_str() {
    if [ -z "${1-}" ]; then
        printf 'null'
    else
        # Escape backslashes and double-quotes; everything else is fine
        # for our values (URLs, slugs, simple identifiers).
        printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
    fi
}

json_bool() {
    case "${1-}" in
        true|TRUE|1|yes) printf 'true' ;;
        *)               printf 'false' ;;
    esac
}

cat > "$OUT" <<EOF
{
    "productName":         $(json_str "${FEEDBOT_PRODUCT_NAME:-Feedbot}"),
    "publicUrl":           $(json_str "${FEEDBOT_PUBLIC_URL:-}"),
    "mcpPublicUrl":        $(json_str "${FEEDBOT_MCP_PUBLIC_URL:-}"),
    "telegramBotUsername": $(json_str "${FEEDBOT_TELEGRAM_BOT_USERNAME:-}"),
    "allowSignup":         $(json_bool "${FEEDBOT_ALLOW_SIGNUP:-false}"),
    "billingEnabled":      $(json_bool "${FEEDBOT_BILLING_ENABLED:-false}"),
    "deployment":          $(json_str "${FEEDBOT_DEPLOYMENT:-self-host}"),
    "buildSha":            $(json_str "${FEEDBOT_BUILD_SHA:-}")
}
EOF

# Be extra defensive about permissions — nginx runs as non-root and
# must be able to read this file.
chmod 644 "$OUT"
