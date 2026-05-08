#!/usr/bin/env sh
# Integration test for bin/feedbot — exercises the read-only paths
# that don't need Docker. Mutating commands (start/stop/restart,
# upgrade, backup, restore, rotate-*, uninstall) are exercised in
# the larger smoke matrix in I12; this test catches regressions in
# argument parsing, workdir resolution, and output formatting on
# every push.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI="${REPO_ROOT}/bin/feedbot"
INSTALLER="${REPO_ROOT}/install.sh"

WORK_DIR="$(mktemp -d -t feedbot-cli-test.XXXXXX 2>/dev/null \
    || mktemp -d 2>/dev/null \
    || echo "/tmp/feedbot-cli-test.$$")"

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

# ── 0. shellcheck clean ────────────────────────────────────────────
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck --shell=bash "$CLI" \
        || { echo "FAIL: shellcheck found issues in bin/feedbot" >&2; exit 1; }
    echo "  ok  shellcheck clean"
fi

# ── 1. --help exits 0 with usage on stdout ─────────────────────────
"$CLI" --help >"$WORK_DIR/help.txt"
grep -q "manage a self-hosted Feedbot deployment" "$WORK_DIR/help.txt" \
    || { echo "FAIL: --help missing tagline" >&2; exit 1; }
for cmd in status start stop restart logs upgrade doctor backup restore \
           rotate-secret-key rotate-bot-token uninstall; do
    grep -q "$cmd" "$WORK_DIR/help.txt" \
        || { echo "FAIL: --help missing '$cmd' subcommand" >&2; exit 1; }
done
echo "  ok  --help lists every subcommand"

# ── 2. Unknown subcommand exits 2 with an actionable hint ──────────
if "$CLI" totally-bogus 2>"$WORK_DIR/err.txt"; then
    echo "FAIL: unknown subcommand should exit non-zero" >&2; exit 1
fi
grep -q "Unknown command" "$WORK_DIR/err.txt" \
    || { echo "FAIL: unknown-command error missing" >&2; exit 1; }
grep -q "feedbot --help" "$WORK_DIR/err.txt" \
    || { echo "FAIL: unknown-command hint missing" >&2; exit 1; }
echo "  ok  unknown subcommand → exit 2 with hint"

# ── 3. Workdir resolution: missing install ─────────────────────────
# Point FEEDBOT_WORKDIR at an empty dir so resolve_workdir falls
# through every candidate and aborts.
if FEEDBOT_WORKDIR="$WORK_DIR/missing" "$CLI" workdir 2>"$WORK_DIR/err.txt"; then
    echo "FAIL: 'workdir' should fail when no install exists" >&2; exit 1
fi
grep -q "No Feedbot install found" "$WORK_DIR/err.txt" \
    || { echo "FAIL: missing-install error missing" >&2; exit 1; }
echo "  ok  no install → actionable error"

# ── 4. Workdir resolution: existing install (built via install.sh) ─
INSTALL_DIR="$WORK_DIR/install"
"$INSTALLER" --dry-run --yes --local --no-cli --workdir="$INSTALL_DIR" \
    >/dev/null 2>&1
[ -f "${INSTALL_DIR}/.install-state" ] \
    || { echo "FAIL: dry-run installer didn't produce .install-state" >&2; exit 1; }

resolved="$(FEEDBOT_WORKDIR="$INSTALL_DIR" "$CLI" workdir)"
[ "$resolved" = "$INSTALL_DIR" ] \
    || { echo "FAIL: workdir resolved to '$resolved' (want '$INSTALL_DIR')" >&2; exit 1; }
echo "  ok  workdir resolves via FEEDBOT_WORKDIR"

# ── 5. config redacts secrets ──────────────────────────────────────
config_out="$(FEEDBOT_WORKDIR="$INSTALL_DIR" "$CLI" config)"
# Each set secret should NOT leak its value.
secret_value="$(grep '^FEEDBOT_SECRET_KEY=' "${INSTALL_DIR}/.env" | cut -d= -f2-)"
case "$config_out" in
    *"$secret_value"*)
        echo "FAIL: 'feedbot config' leaked FEEDBOT_SECRET_KEY value" >&2
        exit 1
        ;;
esac
case "$config_out" in
    *"FEEDBOT_SECRET_KEY=<redacted>"*) : ;;
    *) echo "FAIL: 'feedbot config' didn't redact FEEDBOT_SECRET_KEY" >&2; exit 1 ;;
esac
echo "  ok  config redacts FEEDBOT_SECRET_KEY"

# Empty SMTP_PASSWORD should NOT be tagged <redacted> (that's
# "not configured", not "we hid it from you").
case "$config_out" in
    *"SMTP_PASSWORD=<redacted>"*)
        echo "FAIL: empty SMTP_PASSWORD shown as redacted" >&2; exit 1
        ;;
esac
echo "  ok  config keeps empty fields as-is"

# ── 6. list-backups on a fresh install reports (none) ──────────────
list_out="$(FEEDBOT_WORKDIR="$INSTALL_DIR" "$CLI" list-backups)"
case "$list_out" in
    *"(none)"*) : ;;
    *) echo "FAIL: list-backups didn't report empty state" >&2; exit 1 ;;
esac
echo "  ok  list-backups reports (none) on fresh install"

# After dropping a fake tarball, list-backups picks it up.
mkdir -p "${INSTALL_DIR}/backups"
echo X >"${INSTALL_DIR}/backups/feedbot-20260101T000000Z.tar.gz"
list_out="$(FEEDBOT_WORKDIR="$INSTALL_DIR" "$CLI" list-backups)"
case "$list_out" in
    *"feedbot-20260101T000000Z.tar.gz"*) : ;;
    *) echo "FAIL: list-backups didn't enumerate dropped file" >&2; exit 1 ;;
esac
echo "  ok  list-backups enumerates files"

echo ""
echo "All bin/feedbot tests passed."
