#!/bin/sh
# Faithful playback of install.sh output for VHS recording.
# Mirrors stages 1–13 of install.sh with realistic timing.
set -eu

C_RESET=$(printf '\033[0m')
C_DIM=$(printf '\033[2m')
C_GREEN=$(printf '\033[32m')
C_YELLOW=$(printf '\033[33m')
C_BOLD=$(printf '\033[1m')
C_CYAN=$(printf '\033[36m')
C_MAGENTA=$(printf '\033[35m')

ok()   { printf '  %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '  %s⚠%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
say()  { printf '%s\n' "$*"; }
section() {
    printf '\n  %s%s%s\n  %s\n' "$C_BOLD" "$1" "$C_RESET" \
        "$(printf '─%.0s' $(seq 1 ${#1}))"
}
pause() { sleep "${1:-0.35}"; }

clear
sleep 0.4

# ── Banner ─────────────────────────────────────────────────────────
printf '\n  %sFeedbot installer · v0.2.0%s\n' "$C_BOLD" "$C_RESET"
printf '  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
pause 0.6

# ── Stage 1 ────────────────────────────────────────────────────────
section "Pre-flight checks"
pause 0.25
ok "OS               macOS 15.3"; pause 0.18
ok "Architecture     arm64"; pause 0.18
ok "RAM              16384 MB"; pause 0.18
ok "Disk free        287 GB on /"; pause 0.18
ok "Network          ghcr.io reachable"; pause 0.18
ok "Time sync        skipped (macOS keeps system time)"
pause 0.5

# ── Stage 2 ────────────────────────────────────────────────────────
section "Existing install"
pause 0.25
ok "No previous install detected — fresh install"
pause 0.4

# ── Stage 3 ────────────────────────────────────────────────────────
section "Configuration"
pause 0.25
ok "Mode             ${C_BOLD}local${C_RESET} (binds 127.0.0.1; private to this machine)"
pause 0.18
ok "Install dir      $HOME/.feedbot"
pause 0.55
printf '  Continue with these settings? [Y/n]: '
pause 0.7
printf 'y\n'
pause 0.4

# ── Stage 4 ────────────────────────────────────────────────────────
section "Docker"
pause 0.25
ok "Docker installed (Docker version 27.3.1, build ce12230)"
pause 0.2
ok "docker compose v2 available"
pause 0.4

# ── Stage 5 ────────────────────────────────────────────────────────
section "Ports"
pause 0.25
ok "HTTP port        :80 on 127.0.0.1"
pause 0.4

# ── Stage 6 — image pulls (this is the visual showcase moment) ────
section "Pulling images"
pause 0.3
for img in \
    "ghcr.io/helderpgoncalves/feedbot-api:latest" \
    "ghcr.io/helderpgoncalves/feedbot-web:latest" \
    "ghcr.io/helderpgoncalves/feedbot-bot:latest" \
    "caddy:2-alpine" \
    "postgres:16-alpine"
do
    printf '  pulling %s ... ' "$img"
    sleep 0.55
    printf '%sok%s\n' "$C_GREEN" "$C_RESET"
done
pause 0.45

# ── Stage 7 ────────────────────────────────────────────────────────
section "Workdir"
pause 0.25
ok "Created $HOME/.feedbot"
pause 0.35

# ── Stage 8 ────────────────────────────────────────────────────────
section "Writing config"
pause 0.3
ok "Wrote docker-compose.yml, .env, caddy/Caddyfile, .install-state"
pause 0.4

# ── Stage 9 ────────────────────────────────────────────────────────
section "Starting stack"
pause 0.3
ok "Stack started"
pause 0.35

# ── Stage 10 — spinner moment ─────────────────────────────────────
section "Waiting for stack to come up"
pause 0.2
i=0
while [ $i -lt 7 ]; do
    case $((i % 4)) in
        0) printf '\r  · waiting    ' ;;
        1) printf '\r  ·· waiting   ' ;;
        2) printf '\r  ··· waiting  ' ;;
        3) printf '\r  ···· waiting ' ;;
    esac
    sleep 0.25
    i=$((i + 1))
done
printf '\r                          \r'
ok "Healthy: db, api, web"
pause 0.4

# ── Stage 11 ───────────────────────────────────────────────────────
section "Installing 'feedbot' CLI"
pause 0.25
ok "CLI installed from https://raw.githubusercontent.com/helderpgoncalves/feedbot/main/bin/feedbot"
pause 0.4

# ── Stage 12 ───────────────────────────────────────────────────────
section "Final checks"
pause 0.25
ok "GET http://127.0.0.1:80/"
pause 0.18
ok "GET http://127.0.0.1:80/config.json"
pause 0.18
ok "GET http://127.0.0.1:80/healthz"
pause 0.6

# ── Stage 13 — celebratory summary ────────────────────────────────
say ""
say "  ${C_GREEN}${C_BOLD}✓ Feedbot is running at http://localhost${C_RESET}"
say ""
say "  Workdir:    $HOME/.feedbot"
say "  Mode:       local"
say "  Install log: $HOME/.feedbot/logs/install-20260509T142301Z.log"
say ""
say "  Next steps:"
say "    1. Open ${C_CYAN}http://localhost${C_RESET} and create the owner account."
say "    2. Configure Email, Telegram, Domain & HTTPS in Settings."
say ""
say "  CLI: ${C_DIM}'feedbot status', 'feedbot logs', 'feedbot upgrade'${C_RESET}"
say ""
pause 1.8
