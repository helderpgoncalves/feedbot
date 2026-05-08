#!/usr/bin/env sh
# Integration test for install.sh — exercises the dry-run path end-to-end
# and asserts the emitted file tree + key settings. Runs in CI on every
# push so a regression in the installer can't ship.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALLER="${REPO_ROOT}/install.sh"

WORK_DIR="$(mktemp -d -t feedbot-install-test.XXXXXX 2>/dev/null \
    || mktemp -d 2>/dev/null \
    || echo "/tmp/feedbot-install-test.$$")"

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

# ── 1. --help exits 0 with usage on stdout ──────────────────────────
"$INSTALLER" --help >"$WORK_DIR/help.txt"
grep -q "Feedbot installer" "$WORK_DIR/help.txt" \
    || { echo "FAIL: --help missing banner" >&2; exit 1; }
grep -q -- "--local" "$WORK_DIR/help.txt" \
    || { echo "FAIL: --help missing --local flag docs" >&2; exit 1; }
echo "  ok  --help works"

# ── 2. Unknown flag exits non-zero ──────────────────────────────────
if "$INSTALLER" --bogus 2>"$WORK_DIR/err.txt"; then
    echo "FAIL: --bogus should exit non-zero" >&2; exit 1
fi
grep -q "Unknown flag" "$WORK_DIR/err.txt" \
    || { echo "FAIL: --bogus error message missing" >&2; exit 1; }
echo "  ok  unknown flag rejected"

# ── 3. Dry-run --local writes the expected tree ─────────────────────
LOCAL_DIR="${WORK_DIR}/local"
"$INSTALLER" --dry-run --yes --local --no-cli --workdir="$LOCAL_DIR" >/dev/null

for f in docker-compose.yml .env caddy/Caddyfile .install-state; do
    if [ ! -f "${LOCAL_DIR}/${f}" ]; then
        echo "FAIL: --local mode missing ${LOCAL_DIR}/${f}" >&2; exit 1
    fi
done
echo "  ok  --local emits compose/env/caddy/state"

# Local mode must bind to 127.0.0.1 — the privacy guarantee.
grep -q "FEEDBOT_BIND_HOST=127.0.0.1" "${LOCAL_DIR}/.env" \
    || { echo "FAIL: local mode .env not bound to 127.0.0.1" >&2; exit 1; }
grep -q "FEEDBOT_INSTALL_MODE=local" "${LOCAL_DIR}/.env" \
    || { echo "FAIL: install mode not recorded in .env" >&2; exit 1; }
echo "  ok  --local mode binds to 127.0.0.1"

# .install-state is valid JSON.
python3 -c "import json; json.load(open('${LOCAL_DIR}/.install-state'))" \
    || { echo "FAIL: .install-state is not valid JSON" >&2; exit 1; }
echo "  ok  .install-state is valid JSON"

# Secrets must be present and non-empty (we generate them per-install).
grep -E '^FEEDBOT_SECRET_KEY=.+' "${LOCAL_DIR}/.env" >/dev/null \
    || { echo "FAIL: FEEDBOT_SECRET_KEY missing or empty" >&2; exit 1; }
grep -E '^FEEDBOT_DB_PASSWORD=.+' "${LOCAL_DIR}/.env" >/dev/null \
    || { echo "FAIL: FEEDBOT_DB_PASSWORD missing or empty" >&2; exit 1; }
echo "  ok  secrets generated"

# ── 4. Dry-run --server writes 0.0.0.0 ─────────────────────────────
SERVER_DIR="${WORK_DIR}/server"
FEEDBOT_PUBLIC_IP=1.2.3.4 \
    "$INSTALLER" --dry-run --yes --server --no-cli --workdir="$SERVER_DIR" >/dev/null

grep -q "FEEDBOT_BIND_HOST=0.0.0.0" "${SERVER_DIR}/.env" \
    || { echo "FAIL: server mode .env not bound to 0.0.0.0" >&2; exit 1; }
grep -q "FEEDBOT_PUBLIC_URL=http://1.2.3.4" "${SERVER_DIR}/.env" \
    || { echo "FAIL: server mode .env missing FEEDBOT_PUBLIC_IP override" >&2; exit 1; }
echo "  ok  --server mode binds to 0.0.0.0 with FEEDBOT_PUBLIC_IP override"

# ── 5. compose syntax: docker-compose.yml validates ────────────────
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    (cd "$LOCAL_DIR" && docker compose config >/dev/null) \
        || { echo "FAIL: docker compose config rejected the generated file" >&2; exit 1; }
    echo "  ok  docker compose config validates the generated file"
else
    echo "  skip  docker compose not available (CI image has it)"
fi

# ── 6. shellcheck clean (if available) ─────────────────────────────
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck --shell=sh "$INSTALLER" \
        || { echo "FAIL: shellcheck found issues" >&2; exit 1; }
    echo "  ok  shellcheck clean"
fi

echo ""
echo "All install.sh tests passed."
