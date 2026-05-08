#!/bin/sh
# shellcheck shell=sh
# ─────────────────────────────────────────────────────────────────────
# Feedbot installer — one-liner install of a self-hosted Feedbot stack.
#
# Usage:
#     curl -fsSL https://get.feedbot.dev | sh
#     curl -fsSL https://get.feedbot.dev | sh -s -- --yes --local
#
# Constraints:
#   - POSIX sh-compatible. No bashisms in the bootstrap path.
#   - Self-contained. No follow-up file fetches; only image pulls happen
#     over the network during install.
#   - Safe to `curl … | less` for review before piping to sh.
#
# Layout:
#   1. Helpers (logging, prompts, traps, rollback machinery).
#   2. Stages 1–13 as discrete functions.
#   3. main() drives them in order with rollback on any post-stage-4 fail.
# ─────────────────────────────────────────────────────────────────────

set -eu

INSTALLER_VERSION="0.2.0"
DEFAULT_VERSION_TAG="latest"
GHCR_REGISTRY="ghcr.io/helderpgoncalves"

# ── Globals populated by stages ─────────────────────────────────────
OS=""
ARCH=""
IS_ROOT=0
IS_TTY=0
INSTALL_MODE=""
WORKDIR=""
PUBLIC_URL=""
PUBLIC_HOST=""
HTTP_PORT=""
BIND_HOST=""
LOG_FILE=""
EXIT_REASON=""
NEW_INSTALL=1     # set to 0 by stage 2 if upgrading
ROLLBACK_STACK="" # newline-separated list of "stage_NN_rollback" funcs

# ── Flags / env-var-driven config (parsed in parse_flags) ──────────
FLAG_YES=0
FLAG_DRY_RUN=0
FLAG_VERBOSE=0
FLAG_NO_CLI=0
FLAG_FORCE_MODE=""        # "local" or "server" if --local/--server
FLAG_FORCE_ACTION=""      # "upgrade" or "reinstall"
FLAG_VERSION="$DEFAULT_VERSION_TAG"
FLAG_WORKDIR=""
FLAG_HTTP_PORT=""

# ── Image set, in (image, label) tuples (label is for progress bar) ─
# Caddy + Postgres are public Docker Hub images; the three feedbot ones
# come from the GHCR repo published by the I0 CI workflow.
images_for_pull() {
    cat <<EOF
${GHCR_REGISTRY}/feedbot-api:${FLAG_VERSION}
${GHCR_REGISTRY}/feedbot-web:${FLAG_VERSION}
${GHCR_REGISTRY}/feedbot-bot:${FLAG_VERSION}
caddy:2-alpine
postgres:16-alpine
EOF
}

# ─────────────────────────────────────────────────────────────────────
# 1. Output helpers
# ─────────────────────────────────────────────────────────────────────

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    IS_TTY=1
    C_RESET=$(printf '\033[0m')
    C_DIM=$(printf '\033[2m')
    C_RED=$(printf '\033[31m')
    C_GREEN=$(printf '\033[32m')
    C_YELLOW=$(printf '\033[33m')
    C_BOLD=$(printf '\033[1m')
else
    C_RESET="" C_DIM="" C_RED="" C_GREEN="" C_YELLOW="" C_BOLD=""
fi

# Append a tagged line to the install log (no-op until init_log runs).
# Wrapped as a function so the call sites stay one line and shellcheck
# doesn't flag the A && B || C compound (SC2015) on every helper.
_log() {
    if [ -n "$LOG_FILE" ]; then
        printf '%s\n' "$*" >>"$LOG_FILE" 2>/dev/null || :
    fi
}

# All output helpers also append to the log file (set up in init_log).
say() { printf '%s\n' "$*"; _log "[say] $*"; }
ok()  { printf '  %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; _log "[ok ] $*"; }
warn(){ printf '  %s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; _log "[warn] $*"; }
err() { printf '  %s✗%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; _log "[err] $*"; }
section() {
    printf '\n  %s%s%s\n  %s\n' "$C_BOLD" "$1" "$C_RESET" "$(printf '─%.0s' $(seq 1 ${#1}))"
    _log "=== $1 ==="
}
verbose() {
    if [ "$FLAG_VERBOSE" = "1" ]; then
        printf '%s[debug]%s %s\n' "$C_DIM" "$C_RESET" "$*" >&2
    fi
}
fatal() { err "$*"; EXIT_REASON="$*"; exit 1; }

# Run a command, log it. Honours --verbose and --dry-run.
run() {
    _log "[run] $*"
    verbose "run: $*"
    if [ "$FLAG_DRY_RUN" = "1" ]; then
        printf '%s[dry-run]%s %s\n' "$C_DIM" "$C_RESET" "$*"
        return 0
    fi
    if [ -n "$LOG_FILE" ]; then
        # Tee stdout/stderr into the log so support has the full transcript
        # even after a rollback wipes the workdir.
        "$@" >>"$LOG_FILE" 2>&1
    else
        "$@"
    fi
}

# Run a command and capture stdout. Logged but not piped.
run_capture() {
    _log "[run-capture] $*"
    "$@"
}

# Prompt for input with a default. POSIX read; respects --yes (returns default).
prompt() {
    _label="$1"; _default="${2:-}"
    if [ "$FLAG_YES" = "1" ]; then
        printf '%s\n' "$_default"
        return 0
    fi
    if [ "$IS_TTY" = "0" ]; then
        # Non-interactive (piped from curl with no stdin TTY) and no --yes
        # ⇒ fall back to the default. The user can re-run with flags.
        printf '%s\n' "$_default"
        return 0
    fi
    if [ -n "$_default" ]; then
        printf '  %s [%s]: ' "$_label" "$_default" >&2
    else
        printf '  %s: ' "$_label" >&2
    fi
    # Read from /dev/tty so `curl … | sh` still gets keyboard input.
    _ans=""
    if [ -r /dev/tty ]; then
        read -r _ans </dev/tty || _ans=""
    fi
    [ -z "$_ans" ] && _ans="$_default"
    printf '%s\n' "$_ans"
}

confirm() {
    _label="$1"; _default="${2:-y}"
    _hint="[Y/n]"; [ "$_default" = "n" ] && _hint="[y/N]"
    _ans="$(prompt "$_label $_hint" "$_default")"
    case "$_ans" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────
# 2. Init log file. Done as early as possible so even pre-flight is captured.
# ─────────────────────────────────────────────────────────────────────

init_log() {
    # Detect uid here rather than reading IS_ROOT — main() calls this
    # before stage1_preflight has had a chance to populate IS_ROOT.
    _uid="$(id -u 2>/dev/null || echo 0)"
    _ts="$(date -u +%Y%m%dT%H%M%SZ)"
    if [ "$_uid" = "0" ] && [ -w /var/log ]; then
        LOG_FILE="/var/log/feedbot-install-${_ts}.log"
    else
        # macOS or non-root Linux.
        mkdir -p "${HOME}/.feedbot/logs" 2>/dev/null || true
        LOG_FILE="${HOME}/.feedbot/logs/install-${_ts}.log"
    fi
    : >"$LOG_FILE" 2>/dev/null || LOG_FILE=""
    if [ -n "$LOG_FILE" ]; then
        printf 'feedbot installer %s · %s\n' "$INSTALLER_VERSION" "$(date -u)" >>"$LOG_FILE"
    fi
    return 0
}

# ─────────────────────────────────────────────────────────────────────
# 3. Flag parsing
# ─────────────────────────────────────────────────────────────────────

print_help() {
    cat <<EOF
Feedbot installer ${INSTALLER_VERSION}

Usage:
    curl -fsSL https://get.feedbot.dev | sh
    install.sh [flags]

Flags:
    --yes, -y             Non-interactive: accept all defaults.
    --local               Force LOCAL mode (bind 127.0.0.1 only).
    --server              Force SERVER mode (bind 0.0.0.0).
    --upgrade             Force upgrade path on existing install.
    --reinstall           Force reinstall (DESTROYS data; asks confirm).
    --version=vX.Y.Z      Pin image versions (default: latest).
    --workdir=PATH        Override install location.
    --http-port=N         Override port resolution.
    --no-cli              Skip installing 'feedbot' to PATH.
    --dry-run             Print actions without mutating anything.
    --verbose, -v         Show every command run.
    --help, -h            This message.

Environment-variable equivalents:
    FEEDBOT_INSTALL_MODE     local | server
    FEEDBOT_PUBLIC_IP        Override IP detection (server mode).
    FEEDBOT_WORKDIR          Override install location.
    FEEDBOT_HTTP_PORT        Override port.
    FEEDBOT_VERSION          Pin to specific image tag.
EOF
}

parse_flags() {
    # Pick up env-var fallbacks first; flags override below.
    [ -n "${FEEDBOT_INSTALL_MODE:-}" ] && FLAG_FORCE_MODE="$FEEDBOT_INSTALL_MODE"
    [ -n "${FEEDBOT_WORKDIR:-}" ] && FLAG_WORKDIR="$FEEDBOT_WORKDIR"
    [ -n "${FEEDBOT_HTTP_PORT:-}" ] && FLAG_HTTP_PORT="$FEEDBOT_HTTP_PORT"
    [ -n "${FEEDBOT_VERSION:-}" ] && FLAG_VERSION="$FEEDBOT_VERSION"

    while [ $# -gt 0 ]; do
        case "$1" in
            --yes|-y) FLAG_YES=1 ;;
            --local) FLAG_FORCE_MODE="local" ;;
            --server) FLAG_FORCE_MODE="server" ;;
            --upgrade) FLAG_FORCE_ACTION="upgrade" ;;
            --reinstall) FLAG_FORCE_ACTION="reinstall" ;;
            --no-cli) FLAG_NO_CLI=1 ;;
            --dry-run) FLAG_DRY_RUN=1 ;;
            --verbose|-v) FLAG_VERBOSE=1 ;;
            --help|-h) print_help; exit 0 ;;
            --version=*) FLAG_VERSION="${1#--version=}" ;;
            --workdir=*) FLAG_WORKDIR="${1#--workdir=}" ;;
            --http-port=*) FLAG_HTTP_PORT="${1#--http-port=}" ;;
            *) fatal "Unknown flag: $1 (try --help)" ;;
        esac
        shift
    done

    case "$FLAG_FORCE_MODE" in
        ""|"local"|"server") : ;;
        *) fatal "FEEDBOT_INSTALL_MODE must be 'local' or 'server'" ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────
# 4. Rollback machinery
# Each stage that mutates the system registers a rollback function via
# register_rollback before the mutation. On failure post-stage-4 we run
# them in LIFO order. Rollback failures are logged but never block.
# ─────────────────────────────────────────────────────────────────────

register_rollback() {
    # Prepend so LIFO order on shell-loop iteration. Newline-separated.
    ROLLBACK_STACK="$1
$ROLLBACK_STACK"
}

run_rollback() {
    [ -z "$ROLLBACK_STACK" ] && return 0
    section "Rolling back"
    # Iterate on the stack one line at a time; each line is a function name.
    printf '%s\n' "$ROLLBACK_STACK" | while IFS= read -r _hook; do
        [ -z "$_hook" ] && continue
        warn "rollback: $_hook"
        if ! "$_hook" >>"$LOG_FILE" 2>&1; then
            warn "rollback hook '$_hook' failed (continuing)"
        fi
    done
    say ""
    say "  Install log preserved at: $LOG_FILE"
}

on_exit() {
    _rc=$?
    if [ "$_rc" != "0" ]; then
        err ""
        err "Install failed${EXIT_REASON:+: $EXIT_REASON}"
        run_rollback
    fi
    exit "$_rc"
}
trap on_exit EXIT
trap 'EXIT_REASON="aborted by user (Ctrl-C)"; exit 130' INT

# ─────────────────────────────────────────────────────────────────────
# Stage 1 — Pre-flight checks (read-only)
# ─────────────────────────────────────────────────────────────────────

stage1_preflight() {
    section "Pre-flight checks"
    _failed=0

    # OS
    _kernel="$(uname -s 2>/dev/null || echo unknown)"
    case "$_kernel" in
        Linux) OS="linux"; _osname="$(_linux_pretty_name)" ;;
        Darwin) OS="darwin"; _osname="macOS $(sw_vers -productVersion 2>/dev/null || echo '?')" ;;
        *) err "Unsupported OS: $_kernel"; _failed=1; OS="unknown"; _osname="$_kernel" ;;
    esac
    [ "$OS" != "unknown" ] && ok "OS               $_osname"

    # Architecture
    ARCH="$(uname -m 2>/dev/null || echo unknown)"
    case "$ARCH" in
        x86_64|amd64) ok "Architecture     $ARCH" ;;
        aarch64|arm64) ok "Architecture     $ARCH" ;;
        *) err "Unsupported arch: $ARCH (need x86_64 or arm64)"; _failed=1 ;;
    esac

    # Root status (informational; only used to pick workdir defaults).
    [ "$(id -u 2>/dev/null || echo 0)" = "0" ] && IS_ROOT=1 || IS_ROOT=0

    # Re-init the log now that we know IS_ROOT (the early init may have
    # picked $HOME for a root user; harmless either way).
    [ -z "$LOG_FILE" ] && init_log

    # RAM
    _ram_mb=0
    if [ "$OS" = "linux" ] && [ -r /proc/meminfo ]; then
        _ram_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
        _ram_mb=$(( _ram_kb / 1024 ))
    elif [ "$OS" = "darwin" ]; then
        _ram_b="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
        _ram_mb=$(( _ram_b / 1024 / 1024 ))
    fi
    if [ "$_ram_mb" -ge 2048 ]; then
        ok "RAM              ${_ram_mb} MB"
    elif [ "$_ram_mb" -ge 1024 ]; then
        warn "RAM              ${_ram_mb} MB (low — 2GB+ recommended)"
    else
        err "RAM              ${_ram_mb} MB (need ≥1GB; ≥2GB recommended)"
        _failed=1
    fi

    # Disk free in /tmp (workdir target is decided in stage 3, but a
    # workdir on / typically has the same fs).
    _disk_free_g=0
    if command -v df >/dev/null 2>&1; then
        # df -k → 1024-byte blocks; portable across BSD/GNU.
        _disk_free_kb="$(df -k / 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)"
        _disk_free_g=$(( _disk_free_kb / 1024 / 1024 ))
    fi
    if [ "$_disk_free_g" -ge 5 ]; then
        ok "Disk free        ${_disk_free_g} GB on /"
    else
        err "Disk free        ${_disk_free_g} GB on / (need ≥5GB)"
        _failed=1
    fi

    # DNS + ghcr.io reachability. Use curl if present (it usually is).
    if command -v curl >/dev/null 2>&1; then
        if curl -sSI --max-time 5 https://ghcr.io/v2/ >/dev/null 2>&1; then
            ok "Network          ghcr.io reachable"
        else
            err "Network          can't reach ghcr.io (firewall? offline?)"
            _failed=1
        fi
    else
        warn "Network          curl not found; skipping reachability test"
    fi

    # Time sync (LE rejects clocks more than ~5 minutes off; we warn
    # at 60s so the user can fix it before they enable HTTPS later).
    _drift_ok=1
    if [ "$OS" = "linux" ] && command -v timedatectl >/dev/null 2>&1; then
        if timedatectl status 2>/dev/null | grep -q "synchronized: yes"; then
            ok "Time sync        NTP synced"
        else
            warn "Time sync        not NTP-synced (HTTPS issuance may fail later)"
            _drift_ok=0
        fi
    elif [ "$OS" = "darwin" ]; then
        # macOS keeps time via Apple's NTP; skip rather than over-warn.
        ok "Time sync        skipped (macOS keeps system time)"
    else
        warn "Time sync        couldn't verify"
    fi
    : "$_drift_ok"  # currently advisory only

    if [ "$_failed" = "1" ]; then
        fatal "Pre-flight failed — see errors above."
    fi
}

_linux_pretty_name() {
    if [ -r /etc/os-release ]; then
        # POSIX-friendly extraction of PRETTY_NAME.
        sed -n 's/^PRETTY_NAME="\(.*\)"$/\1/p' /etc/os-release | head -n 1
    else
        echo "Linux $(uname -r 2>/dev/null || echo)"
    fi
}

# ─────────────────────────────────────────────────────────────────────
# Stage 2 — Detect existing install
# ─────────────────────────────────────────────────────────────────────

stage2_detect_existing() {
    section "Existing install"

    _existing=""
    for _candidate in /opt/feedbot "${HOME}/.feedbot"; do
        if [ -f "${_candidate}/.install-state" ]; then
            _existing="$_candidate"
            break
        fi
    done
    if [ -n "${FLAG_WORKDIR:-}" ] && [ -f "${FLAG_WORKDIR}/.install-state" ]; then
        _existing="$FLAG_WORKDIR"
    fi

    if [ -z "$_existing" ]; then
        ok "No previous install detected — fresh install"
        NEW_INSTALL=1
        return 0
    fi

    NEW_INSTALL=0
    WORKDIR="$_existing"
    say "  Found existing install at $C_BOLD$_existing$C_RESET"

    if [ -n "$FLAG_FORCE_ACTION" ]; then
        _action="$FLAG_FORCE_ACTION"
    else
        say ""
        say "  What would you like to do?"
        say "    1) Upgrade — pull newest images, preserve all data"
        say "    2) Reconfigure — re-run wizard (mode/port), keep data"
        say "    3) Reinstall — DESTROYS ALL DATA"
        say "    4) Cancel"
        _ans="$(prompt "Choose [1-4]" "1")"
        case "$_ans" in
            1|"") _action="upgrade" ;;
            2) _action="reconfigure" ;;
            3) _action="reinstall" ;;
            4) EXIT_REASON="cancelled by user"; exit 0 ;;
            *) fatal "Invalid choice: $_ans" ;;
        esac
    fi

    case "$_action" in
        upgrade)
            ok "Action: upgrade — keeping data, pulling latest images"
            FLAG_FORCE_ACTION="upgrade"
            ;;
        reconfigure)
            ok "Action: reconfigure — running wizard again"
            FLAG_FORCE_ACTION="reconfigure"
            ;;
        reinstall)
            warn "Action: reinstall — this will DELETE all data."
            if ! confirm "Type 'yes' to confirm REINSTALL" "n"; then
                EXIT_REASON="reinstall cancelled"; exit 0
            fi
            FLAG_FORCE_ACTION="reinstall"
            NEW_INSTALL=1   # treat as new install for the rest of the run
            ;;
        *) fatal "Unknown action: $_action" ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────
# Stage 3 — Auto-detect mode + 3-prompt wizard
# ─────────────────────────────────────────────────────────────────────

stage3_collect_config() {
    section "Configuration"

    _detect_mode

    # Workdir: macOS → ~/.feedbot, root linux → /opt/feedbot, non-root linux → ~/.feedbot.
    if [ -z "$WORKDIR" ]; then
        if [ -n "$FLAG_WORKDIR" ]; then
            WORKDIR="$FLAG_WORKDIR"
        elif [ "$OS" = "darwin" ]; then
            WORKDIR="${HOME}/.feedbot"
        elif [ "$IS_ROOT" = "1" ] || [ "$INSTALL_MODE" = "server" ]; then
            WORKDIR="/opt/feedbot"
        else
            WORKDIR="${HOME}/.feedbot"
        fi
    fi

    # Final confirmation prompt + workdir override.
    say ""
    if [ "$INSTALL_MODE" = "server" ]; then
        ok "Mode             $C_BOLD${INSTALL_MODE}$C_RESET (binds 0.0.0.0; reachable on $PUBLIC_HOST)"
    else
        ok "Mode             $C_BOLD${INSTALL_MODE}$C_RESET (binds 127.0.0.1; private to this machine)"
    fi
    ok "Install dir      $WORKDIR"

    # Only ask for workdir confirmation in interactive runs.
    if [ "$FLAG_YES" = "0" ] && [ "$IS_TTY" = "1" ] && [ -z "$FLAG_WORKDIR" ]; then
        _typed="$(prompt "Install location" "$WORKDIR")"
        if [ -n "$_typed" ] && [ "$_typed" != "$WORKDIR" ]; then
            WORKDIR="$_typed"
            ok "Install dir      $WORKDIR (overridden)"
        fi
    fi

    # Validate writable parent.
    _parent="$(dirname "$WORKDIR")"
    if [ ! -d "$_parent" ]; then
        run mkdir -p "$_parent" || fatal "Cannot create parent directory $_parent"
    fi
    if [ ! -w "$_parent" ]; then
        fatal "Parent directory $_parent is not writable. Re-run with sudo or pick a different --workdir."
    fi

    # Final confirmation.
    say ""
    if ! confirm "Continue with these settings?" "y"; then
        EXIT_REASON="cancelled at confirmation"
        exit 0
    fi
}

_detect_mode() {
    # Resolution order: explicit flag/env, OS rule, public IP detection.
    if [ -n "$FLAG_FORCE_MODE" ]; then
        INSTALL_MODE="$FLAG_FORCE_MODE"
        verbose "mode forced to $INSTALL_MODE via flag/env"
    elif [ "$OS" = "darwin" ]; then
        INSTALL_MODE="local"
        verbose "macOS → mode=local"
    else
        # Linux: try public-IP heuristic.
        _pub=""
        if command -v curl >/dev/null 2>&1; then
            _pub="$(curl -fsS4 --max-time 3 https://ifconfig.me 2>/dev/null || true)"
        fi
        # Strip whitespace.
        _pub="$(printf '%s' "$_pub" | tr -d '[:space:]')"
        # Collect this host's IPv4 addresses.
        _local_ips=""
        if command -v ip >/dev/null 2>&1; then
            _local_ips="$(ip -4 -o addr show 2>/dev/null | awk '{print $4}' | sed 's|/.*||')"
        elif command -v ifconfig >/dev/null 2>&1; then
            _local_ips="$(ifconfig 2>/dev/null | awk '/inet / {print $2}')"
        fi
        if [ -z "$_pub" ]; then
            INSTALL_MODE="local"
            verbose "no public IP detected → mode=local"
        elif printf '%s\n' "$_local_ips" | grep -qx "$_pub"; then
            INSTALL_MODE="server"
            PUBLIC_HOST="$_pub"
            verbose "public IP $_pub matches a local interface → mode=server"
        else
            # Ambiguous — typical NAT case. Ask.
            warn "Network          public IP $_pub detected but not on this machine"
            say ""
            say "  We detected a public IP but it doesn't belong to this machine —"
            say "  this is the typical home/office router with NAT case."
            say ""
            say "  How do you plan to use Feedbot?"
            say "    1) On this machine only — keep it private (recommended)"
            say "    2) Reachable from the internet (you'll need to forward a port"
            say "       on your router and likely point a domain at the public IP)"
            say "    3) Cancel"
            _ans="$(prompt "Choose [1/2/3]" "1")"
            case "$_ans" in
                ""|1) INSTALL_MODE="local" ;;
                2) INSTALL_MODE="server"; PUBLIC_HOST="$_pub" ;;
                3) EXIT_REASON="cancelled at mode prompt"; exit 0 ;;
                *) fatal "Invalid choice: $_ans" ;;
            esac
        fi
    fi

    if [ "$INSTALL_MODE" = "local" ]; then
        BIND_HOST="127.0.0.1"
        PUBLIC_HOST="localhost"
    else
        BIND_HOST="0.0.0.0"
        if [ -n "${FEEDBOT_PUBLIC_IP:-}" ]; then
            PUBLIC_HOST="$FEEDBOT_PUBLIC_IP"
        elif [ -z "$PUBLIC_HOST" ]; then
            PUBLIC_HOST="${PUBLIC_HOST:-0.0.0.0}"
        fi
    fi
}

# ─────────────────────────────────────────────────────────────────────
# Stage 4 — Ensure Docker
# ─────────────────────────────────────────────────────────────────────

stage4_ensure_docker() {
    section "Docker"

    if command -v docker >/dev/null 2>&1; then
        _ver="$(docker --version 2>/dev/null || true)"
        ok "Docker installed ($_ver)"
        if ! docker info >/dev/null 2>&1; then
            if [ "$OS" = "darwin" ]; then
                err "Docker is installed but the daemon is not running."
                err "Start Docker Desktop (Applications → Docker) and re-run."
                fatal "Docker daemon not running"
            fi
            fatal "Docker is installed but the daemon is not running. Start it (e.g. 'sudo systemctl start docker') and re-run."
        fi
        # Compose v2 plugin.
        if ! docker compose version >/dev/null 2>&1; then
            fatal "docker compose v2 not found. Install the docker-compose-plugin package."
        fi
        ok "docker compose v2 available"
        return 0
    fi

    if [ "$OS" = "darwin" ]; then
        err "Docker is not installed."
        err "Install Docker Desktop:"
        err "    brew install --cask docker"
        err "    (or download from https://www.docker.com/products/docker-desktop/)"
        err "Then start Docker Desktop and re-run this installer."
        fatal "Docker missing on macOS"
    fi

    # Linux: offer to install via the official convenience script.
    say "  Docker is not installed. We can install it via the official"
    say "  https://get.docker.com convenience script."
    if confirm "Install Docker now?" "y"; then
        if [ "$IS_ROOT" != "1" ] && ! command -v sudo >/dev/null 2>&1; then
            fatal "Need root or sudo to install Docker. Run as root or install Docker manually."
        fi
        _docker_install_cmd="curl -fsSL https://get.docker.com | sh"
        [ "$IS_ROOT" != "1" ] && _docker_install_cmd="curl -fsSL https://get.docker.com | sudo sh"
        warn "Running: $_docker_install_cmd"
        # We can't use run() — it does word-splitting on positional args
        # and this is a pipe. Just exec via sh -c with logging.
        if [ -n "$LOG_FILE" ]; then
            sh -c "$_docker_install_cmd" >>"$LOG_FILE" 2>&1 || fatal "Docker install failed; see $LOG_FILE"
        else
            sh -c "$_docker_install_cmd" || fatal "Docker install failed"
        fi
        ok "Docker installed via get.docker.com"
        if ! docker compose version >/dev/null 2>&1; then
            fatal "docker compose v2 not found post-install. Install docker-compose-plugin and re-run."
        fi
    else
        say ""
        say "  To install Docker manually:"
        say "    https://docs.docker.com/engine/install/"
        fatal "Docker is required"
    fi
}

# ─────────────────────────────────────────────────────────────────────
# Stage 5 — Resolve ports
# ─────────────────────────────────────────────────────────────────────

stage5_resolve_ports() {
    section "Ports"
    _candidate="${FLAG_HTTP_PORT:-80}"
    if _port_busy "$_candidate"; then
        warn "Port :${_candidate} is in use on ${BIND_HOST}"
        if [ "$FLAG_YES" = "1" ]; then
            # Auto-fallback in non-interactive mode.
            _candidate="$(_find_free_port 8080)" \
                || fatal "Could not find a free port (tried 8080-8090)"
            warn "Auto-selected port $_candidate"
        else
            say ""
            say "  Options:"
            say "    1) Use port 8080 (or next free)"
            say "    2) Cancel and free :${_candidate} yourself"
            _ans="$(prompt "Choose [1/2]" "1")"
            case "$_ans" in
                ""|1)
                    _candidate="$(_find_free_port 8080)" \
                        || fatal "Could not find a free port (tried 8080-8090)"
                    ;;
                *) EXIT_REASON="cancelled at port prompt"; exit 0 ;;
            esac
        fi
    fi
    HTTP_PORT="$_candidate"
    ok "HTTP port        :${HTTP_PORT} on ${BIND_HOST}"

    if [ "$INSTALL_MODE" = "local" ]; then
        PUBLIC_URL="http://localhost"
        [ "$HTTP_PORT" != "80" ] && PUBLIC_URL="http://localhost:${HTTP_PORT}"
    else
        PUBLIC_URL="http://${PUBLIC_HOST}"
        [ "$HTTP_PORT" != "80" ] && PUBLIC_URL="http://${PUBLIC_HOST}:${HTTP_PORT}"
    fi
    return 0
}

_port_busy() {
    _p="$1"
    if command -v ss >/dev/null 2>&1; then
        # GNU ss — most reliable on modern Linux.
        ss -ltn "sport = :${_p}" 2>/dev/null | awk 'NR>1' | grep -q . && return 0
        return 1
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"${_p}" -sTCP:LISTEN >/dev/null 2>&1 && return 0
        return 1
    fi
    if command -v netstat >/dev/null 2>&1; then
        netstat -an 2>/dev/null | awk '{print $4}' | grep -Eq "[.:]${_p}\$" && return 0
        return 1
    fi
    # No tool — assume free; the docker bind will fail loudly later.
    return 1
}

_find_free_port() {
    _start="${1:-8080}"
    _i=0
    while [ $_i -lt 11 ]; do
        _try=$((_start + _i))
        if ! _port_busy "$_try"; then
            printf '%s\n' "$_try"
            return 0
        fi
        _i=$((_i + 1))
    done
    return 1
}

# ─────────────────────────────────────────────────────────────────────
# Stage 6 — Pull images
# ─────────────────────────────────────────────────────────────────────

PULLED_IMAGES_FILE=""

stage6_pull_images() {
    section "Pulling images"
    # Track images we fetched (vs. already-cached) in a tmp file so the
    # rollback can clean up only what we added. A pipeline-fed `while`
    # would run in a subshell and lose any var mutations.
    PULLED_IMAGES_FILE="$(mktemp -t feedbot-pulled.XXXXXX 2>/dev/null \
        || mktemp 2>/dev/null \
        || echo "/tmp/feedbot-pulled.$$")"
    : >"$PULLED_IMAGES_FILE"
    register_rollback rollback_stage6

    # Build the image list as a quoted-args string the for-loop can
    # iterate without entering a subshell.
    _images="$(images_for_pull)"
    # POSIX shell word-splitting on whitespace handles one-image-per-line.
    for _img in $_images; do
        [ -z "$_img" ] && continue
        if ! docker image inspect "$_img" >/dev/null 2>&1; then
            verbose "image not present locally: $_img"
            printf '%s\n' "$_img" >>"$PULLED_IMAGES_FILE"
        fi
        printf '  pulling %s ... ' "$_img"
        if run docker pull "$_img"; then
            printf '%sok%s\n' "$C_GREEN" "$C_RESET"
        else
            printf '%sfailed%s\n' "$C_RED" "$C_RESET"
            fatal "Pull failed for $_img — check connectivity or version tag."
        fi
    done
}

rollback_stage6() {
    [ -z "$PULLED_IMAGES_FILE" ] || [ ! -f "$PULLED_IMAGES_FILE" ] && return 0
    while IFS= read -r _img; do
        [ -z "$_img" ] && continue
        docker image rm "$_img" >/dev/null 2>&1 || true
    done <"$PULLED_IMAGES_FILE"
    rm -f "$PULLED_IMAGES_FILE"
}

# ─────────────────────────────────────────────────────────────────────
# Stage 7 — Create workdir + pre-install snapshot
# ─────────────────────────────────────────────────────────────────────

stage7_create_workdir() {
    section "Workdir"
    register_rollback rollback_stage7

    # Snapshot any pre-existing managed files for rollback (only matters
    # when --reinstall: stage 2 wouldn't have allowed us here otherwise).
    # ``mkdir -p`` and ``cp`` are idempotent + cheap; run them even in
    # dry-run so the user can inspect the resulting tree.
    if [ -d "$WORKDIR" ]; then
        mkdir -p "${WORKDIR}/.pre-install"
        for _f in docker-compose.yml .env .install-state caddy/Caddyfile; do
            if [ -f "${WORKDIR}/${_f}" ]; then
                mkdir -p "${WORKDIR}/.pre-install/$(dirname "$_f")"
                cp -p "${WORKDIR}/${_f}" "${WORKDIR}/.pre-install/${_f}"
            fi
        done
    fi

    mkdir -p "$WORKDIR" "${WORKDIR}/caddy/data" "${WORKDIR}/caddy/config" \
        "${WORKDIR}/postgres/data" "${WORKDIR}/backups"
    ok "Created $WORKDIR"
    return 0
}

rollback_stage7() {
    # Only wipe the workdir if we created it fresh in this run.
    [ "$NEW_INSTALL" = "1" ] || return 0
    if [ -n "$WORKDIR" ] && [ -d "$WORKDIR" ]; then
        rm -rf "$WORKDIR"
    fi
    return 0
}

# ─────────────────────────────────────────────────────────────────────
# Stage 8 — Write files
# ─────────────────────────────────────────────────────────────────────

stage8_write_files() {
    section "Writing config"
    register_rollback rollback_stage8

    _secret_key="$(_rand_b64 48)"
    _bot_token="$(_rand_b64 32)"
    _db_password="$(_rand_b64 24 | tr -d '/+=' | cut -c1-24)"

    _write_compose_file
    _write_env_file "$_secret_key" "$_bot_token" "$_db_password"
    _write_caddyfile
    _write_install_state
    ok "Wrote docker-compose.yml, .env, caddy/Caddyfile, .install-state"
}

rollback_stage8() {
    # If a pre-install snapshot exists, restore it.
    if [ -d "${WORKDIR}/.pre-install" ]; then
        for _f in docker-compose.yml .env .install-state caddy/Caddyfile; do
            if [ -f "${WORKDIR}/.pre-install/${_f}" ]; then
                cp -p "${WORKDIR}/.pre-install/${_f}" "${WORKDIR}/${_f}" 2>/dev/null || true
            fi
        done
    fi
}

_rand_b64() {
    _len="$1"
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -base64 "$_len" | tr -d '\n'
    else
        # /dev/urandom + base64 fallback (POSIX-ish).
        head -c "$_len" /dev/urandom | base64 | tr -d '\n='
    fi
}

_write_compose_file() {
    cat >"${WORKDIR}/docker-compose.yml" <<EOF
# Generated by feedbot installer ${INSTALLER_VERSION}.
# Do not edit by hand — use the dashboard's Settings UI or 'feedbot reconfigure'.
name: feedbot

x-defaults: &defaults
  restart: unless-stopped
  init: true
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"
  networks: [feedbot]

services:
  caddy:
    <<: *defaults
    image: caddy:2-alpine
    labels:
      com.feedbot.installer: "true"
      com.feedbot.role: "proxy"
    ports:
      - "\${FEEDBOT_BIND_HOST:-127.0.0.1}:\${FEEDBOT_HTTP_PORT:-80}:80"
      - "\${FEEDBOT_BIND_HOST:-127.0.0.1}:\${FEEDBOT_HTTPS_PORT:-443}:443"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - ./caddy/data:/data
      - ./caddy/config:/config
    depends_on:
      api: { condition: service_started }
      web: { condition: service_started }

  web:
    <<: *defaults
    image: ${GHCR_REGISTRY}/feedbot-web:${FLAG_VERSION}
    labels:
      com.feedbot.installer: "true"
      com.feedbot.role: "web"
    environment:
      FEEDBOT_PRODUCT_NAME: "Feedbot"
      FEEDBOT_PUBLIC_URL: "\${FEEDBOT_PUBLIC_URL}"
      FEEDBOT_DEPLOYMENT: "self-host"
      FEEDBOT_ALLOW_SIGNUP: "false"
      FEEDBOT_BILLING_ENABLED: "false"
      FEEDBOT_TELEGRAM_BOT_USERNAME: "\${FEEDBOT_TELEGRAM_BOT_USERNAME:-}"
    expose: ["80"]
    depends_on:
      api: { condition: service_started }

  api:
    <<: *defaults
    image: ${GHCR_REGISTRY}/feedbot-api:${FLAG_VERSION}
    labels:
      com.feedbot.installer: "true"
      com.feedbot.role: "api"
    env_file: .env
    environment:
      DATABASE_URL: "postgresql+asyncpg://feedbot:\${FEEDBOT_DB_PASSWORD}@db:5432/feedbot"
      FEEDBOT_DEPLOYMENT: "self-host"
    volumes:
      # The orchestrator mounts the docker socket so 'Settings → System →
      # Restart' / 'Update now' / 'Backups' can drive the host stack.
      # See SECURITY.md for the boundary discussion.
      - /var/run/docker.sock:/var/run/docker.sock
      # The orchestrator rewrites .env on Settings changes; mount it
      # in so the API can write through to the same file compose reads.
      - ./.env:/app/.env
      - ./backups:/app/backups
    expose: ["8000"]
    depends_on:
      db: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=3).status==200 else 1)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s

  bot:
    <<: *defaults
    profiles: ["bot"]
    image: ${GHCR_REGISTRY}/feedbot-bot:${FLAG_VERSION}
    labels:
      com.feedbot.installer: "true"
      com.feedbot.role: "bot"
    env_file: .env
    environment:
      FEEDBOT_API_URL: "http://api:8000"
    depends_on:
      api: { condition: service_started }

  db:
    <<: *defaults
    image: postgres:16-alpine
    labels:
      com.feedbot.installer: "true"
      com.feedbot.role: "db"
    environment:
      POSTGRES_USER: feedbot
      POSTGRES_PASSWORD: "\${FEEDBOT_DB_PASSWORD}"
      POSTGRES_DB: feedbot
    volumes:
      - ./postgres/data:/var/lib/postgresql/data
    expose: ["5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U feedbot"]
      interval: 5s
      timeout: 3s
      retries: 10

networks:
  feedbot:
    name: feedbot_net
EOF
}

_write_env_file() {
    _secret="$1"; _bot="$2"; _dbpw="$3"
    cat >"${WORKDIR}/.env" <<EOF
# ─────────────────────────────────────────────────────────────
# Generated by feedbot installer ${INSTALLER_VERSION}.
# Edit via the dashboard's Settings page — manual changes to
# managed keys (SMTP_*, TELEGRAM_*, EMAIL_BACKEND) are reverted
# the next time you save in the UI.
# ─────────────────────────────────────────────────────────────
FEEDBOT_VERSION=${FLAG_VERSION}

# ── Install mode + binding ─────────────────────────────────
FEEDBOT_INSTALL_MODE=${INSTALL_MODE}
FEEDBOT_BIND_HOST=${BIND_HOST}
FEEDBOT_HTTP_PORT=${HTTP_PORT}
FEEDBOT_HTTPS_PORT=443

# ── Public URLs ─────────────────────────────────────────────
FEEDBOT_PUBLIC_URL=${PUBLIC_URL}
FEEDBOT_BASE_URL=${PUBLIC_URL}

# ── Secrets (rotate via 'feedbot rotate-secrets') ──────────
FEEDBOT_SECRET_KEY=${_secret}
FEEDBOT_BOT_TOKEN=${_bot}
FEEDBOT_DB_PASSWORD=${_dbpw}

# ── Managed by orchestrator on Settings save ───────────────
EMAIL_BACKEND=console
SMTP_HOST=
SMTP_PORT=465
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
TELEGRAM_BOT_TOKEN=
FEEDBOT_TELEGRAM_BOT_USERNAME=
EOF
    chmod 600 "${WORKDIR}/.env" 2>/dev/null || true
}

_write_caddyfile() {
    cat >"${WORKDIR}/caddy/Caddyfile" <<'EOF'
# Generated by feedbot installer.
# After install, the dashboard's Settings → Domain & HTTPS page
# regenerates this via Caddy's Admin API on :2019.

{
    auto_https off
    servers {
        trusted_proxies static private_ranges
    }
}

:80 {
    encode gzip zstd

    @api path /api/* /api
    handle @api {
        uri strip_prefix /api
        reverse_proxy api:8000 {
            header_up Host {http.reverse_proxy.upstream.host}
            header_up X-Real-IP {remote}
            header_up X-Forwarded-For {remote}
            header_up X-Forwarded-Proto {scheme}
        }
    }

    @mcp path /mcp /mcp/*
    handle @mcp { reverse_proxy api:8000 }

    @healthz path /healthz
    handle @healthz { reverse_proxy api:8000 }

    handle { reverse_proxy web:80 }

    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "interest-cohort=(), camera=(), microphone=(), geolocation=()"
        Cross-Origin-Opener-Policy "same-origin"
    }
}
EOF
}

_write_install_state() {
    _ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    cat >"${WORKDIR}/.install-state" <<EOF
{
  "schema_version": 1,
  "installer_version": "${INSTALLER_VERSION}",
  "installed_at": "${_ts}",
  "workdir": "${WORKDIR}",
  "platform": {
    "os": "${OS}",
    "arch": "${ARCH}"
  },
  "config": {
    "mode": "${INSTALL_MODE}",
    "bind_host": "${BIND_HOST}",
    "http_port": ${HTTP_PORT},
    "public_url": "${PUBLIC_URL}",
    "version": "${FLAG_VERSION}"
  },
  "managed_files": [
    "docker-compose.yml",
    ".env",
    "caddy/Caddyfile",
    ".install-state"
  ]
}
EOF
}

# ─────────────────────────────────────────────────────────────────────
# Stage 9 — Start stack
# ─────────────────────────────────────────────────────────────────────

stage9_start_stack() {
    section "Starting stack"
    register_rollback rollback_stage9
    cd "$WORKDIR" || fatal "Cannot cd to $WORKDIR"
    if ! run docker compose up -d; then
        fatal "docker compose up failed — see $LOG_FILE"
    fi
    ok "Stack started"
}

rollback_stage9() {
    [ -d "$WORKDIR" ] || return 0
    cd "$WORKDIR" 2>/dev/null || return 0
    docker compose down -v >/dev/null 2>&1 || true
}

# ─────────────────────────────────────────────────────────────────────
# Stage 10 — Wait healthy
# ─────────────────────────────────────────────────────────────────────

stage10_wait_healthy() {
    section "Waiting for stack to come up"
    cd "$WORKDIR" || fatal "Cannot cd to $WORKDIR"
    _deadline=$(( $(date +%s) + 90 ))
    _printed_dots=0

    while [ "$(date +%s)" -lt "$_deadline" ]; do
        # Postgres ready?
        if ! docker compose exec -T db pg_isready -U feedbot >/dev/null 2>&1; then
            _spin "$_printed_dots"; _printed_dots=$((_printed_dots + 1))
            sleep 2
            continue
        fi
        # API healthz?
        if ! curl -fsS --max-time 3 "http://${BIND_HOST}:${HTTP_PORT}/healthz" >/dev/null 2>&1; then
            _spin "$_printed_dots"; _printed_dots=$((_printed_dots + 1))
            sleep 2
            continue
        fi
        # Web config.json?
        if ! curl -fsS --max-time 3 "http://${BIND_HOST}:${HTTP_PORT}/config.json" >/dev/null 2>&1; then
            _spin "$_printed_dots"; _printed_dots=$((_printed_dots + 1))
            sleep 2
            continue
        fi
        printf '\n'
        ok "Healthy: db, api, web"
        return 0
    done

    printf '\n'
    err "Stack did not become healthy within 90s. Recent logs:"
    docker compose logs --tail=50 api 2>&1 | sed 's/^/    /' || true
    fatal "Stack failed health checks"
}

_spin() {
    case $(( $1 % 4 )) in
        0) printf '\r  · waiting' ;;
        1) printf '\r  ·· waiting' ;;
        2) printf '\r  ··· waiting' ;;
        3) printf '\r  ···· waiting' ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────
# Stage 11 — Install CLI
#
# The canonical CLI ships at ``bin/feedbot`` in the repo. We fetch it
# from GitHub raw at the version pinned by ``--version`` (defaults to
# ``main`` for the floating ``latest`` tag). On any fetch failure we
# fall back to a tiny inline shim so the install never blocks on a
# transient network blip — the user can re-run ``feedbot self-update``
# later to get the full CLI.
# ─────────────────────────────────────────────────────────────────────

# Repo + branch/tag the CLI is fetched from.
CLI_REPO="helderpgoncalves/feedbot"
CLI_PATH=""

stage11_install_cli() {
    [ "$FLAG_NO_CLI" = "1" ] && return 0
    section "Installing 'feedbot' CLI"
    register_rollback rollback_stage11

    _target="/usr/local/bin/feedbot"
    if [ "$IS_ROOT" != "1" ] && [ ! -w "$(dirname "$_target")" ]; then
        _target="${HOME}/.feedbot/bin/feedbot"
        run mkdir -p "$(dirname "$_target")"
    fi

    # The "latest" floating tag corresponds to whatever's on main.
    # Pinned versions (vX.Y.Z) fetch the exact tag from GitHub.
    _ref="main"
    case "$FLAG_VERSION" in
        latest|"") _ref="main" ;;
        *) _ref="$FLAG_VERSION" ;;
    esac
    _cli_url="https://raw.githubusercontent.com/${CLI_REPO}/${_ref}/bin/feedbot"

    if curl -fsSL --max-time 15 "$_cli_url" -o "$_target" 2>/dev/null \
        && [ -s "$_target" ]; then
        chmod +x "$_target"
        ok "CLI installed from $_cli_url"
    else
        warn "Couldn't fetch full CLI from GitHub; installing minimal shim."
        warn "Run 'feedbot self-update' once you're online to get the full CLI."
        _write_cli_shim "$_target"
    fi

    CLI_PATH="$_target"
    case ":$PATH:" in
        *":$(dirname "$_target"):"*) : ;;
        *) warn "Add $(dirname "$_target") to your PATH to use 'feedbot' from anywhere." ;;
    esac
}

_write_cli_shim() {
    _target="$1"
    cat >"$_target" <<EOF
#!/bin/sh
# Fallback feedbot CLI shim — install.sh couldn't fetch the full
# CLI from GitHub. Run 'feedbot self-update' to refresh.
set -eu
WORKDIR="${WORKDIR}"
[ ! -d "\$WORKDIR" ] && {
    printf 'Feedbot workdir not found at %s\n' "\$WORKDIR" >&2
    exit 1
}
cd "\$WORKDIR"
case "\${1:-}" in
    ""|status) docker compose ps ;;
    logs) shift; docker compose logs --tail=100 -f "\$@" ;;
    restart) shift; docker compose restart "\$@" ;;
    start) docker compose up -d ;;
    stop) docker compose down ;;
    upgrade) docker compose pull && docker compose up -d ;;
    workdir) printf '%s\n' "\$WORKDIR" ;;
    self-update) curl -fsSL https://get.feedbot.dev | sh -s -- --upgrade --yes ;;
    version)
        if [ -f .install-state ]; then
            sed -n 's/.*"installer_version": "\\(.*\\)".*/\\1/p' .install-state | head -1
        fi ;;
    *)
        printf 'Usage: feedbot {status|logs|restart|start|stop|upgrade|self-update|workdir|version}\n' >&2
        exit 2 ;;
esac
EOF
    chmod +x "$_target"
}

rollback_stage11() {
    if [ -n "$CLI_PATH" ] && [ -f "$CLI_PATH" ]; then
        rm -f "$CLI_PATH"
    fi
    return 0
}

# ─────────────────────────────────────────────────────────────────────
# Stage 12 — Final verification
# ─────────────────────────────────────────────────────────────────────

stage12_final_verify() {
    section "Final checks"
    _base="http://${BIND_HOST}:${HTTP_PORT}"
    for _path in "/" "/config.json" "/healthz"; do
        if curl -fsS --max-time 5 "${_base}${_path}" >/dev/null 2>&1; then
            ok "GET ${_base}${_path}"
        else
            err "GET ${_base}${_path} failed"
            fatal "Final verification failed"
        fi
    done
}

# ─────────────────────────────────────────────────────────────────────
# Stage 13 — Print summary
# ─────────────────────────────────────────────────────────────────────

stage13_summary() {
    say ""
    say "  ${C_GREEN}${C_BOLD}✓ Feedbot is running at ${PUBLIC_URL}${C_RESET}"
    say ""
    say "  Workdir:    $WORKDIR"
    say "  Mode:       $INSTALL_MODE"
    say "  Install log: $LOG_FILE"
    say ""
    say "  Next steps:"
    say "    1. Open ${PUBLIC_URL} and create the owner account."
    say "    2. Configure Email, Telegram, Domain & HTTPS in Settings."
    if [ "$INSTALL_MODE" = "server" ]; then
        say "    3. Add a domain via Settings → Domain & HTTPS to enable TLS."
    fi
    say ""
    say "  CLI: 'feedbot status', 'feedbot logs', 'feedbot upgrade'"
}

# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

main() {
    parse_flags "$@"

    # Print banner.
    printf '\n  %sFeedbot installer · v%s%s\n' "$C_BOLD" "$INSTALLER_VERSION" "$C_RESET"
    printf '  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
    [ "$FLAG_DRY_RUN" = "1" ] && warn "DRY-RUN: no mutations will be made"

    init_log
    stage1_preflight
    stage2_detect_existing
    stage3_collect_config

    # Past stage 3 we start mutating; any failure now triggers rollback.
    stage4_ensure_docker
    stage5_resolve_ports
    stage6_pull_images
    stage7_create_workdir
    stage8_write_files

    # Export env vars compose needs to pick up our values.
    export FEEDBOT_BIND_HOST="$BIND_HOST"
    export FEEDBOT_HTTP_PORT="$HTTP_PORT"
    export FEEDBOT_PUBLIC_URL="$PUBLIC_URL"

    if [ "$FLAG_DRY_RUN" = "1" ]; then
        # In dry-run we have produced the workdir + templated files for
        # inspection but stop before mutating Docker / installing the CLI.
        say ""
        warn "DRY-RUN complete. Inspect $WORKDIR and re-run without --dry-run."
        ROLLBACK_STACK=""
        return 0
    fi

    stage9_start_stack
    stage10_wait_healthy
    stage11_install_cli
    stage12_final_verify
    stage13_summary

    # Past this point, success — clear the rollback stack so the on_exit
    # trap doesn't fire it on a clean exit.
    ROLLBACK_STACK=""
}

main "$@"
