# ─────────────────────────────────────────────────────────────────────
#  Feedbot — install.sh showcase tape
#
#  A pixel-faithful clone of what `curl -fsSL https://get.feedbot.dev | sh`
#  prints on a fresh macOS box. No visible prompt, no script invocation,
#  no shell artifacts — pure installer output, brand-themed.
#
#  Renders three artifacts:
#    docs/assets/install.gif   — README embed (GitHub-renderable)
#    docs/assets/install.mp4   — landing page (autoplay-friendly)
#    docs/assets/install.webm  — landing page (smaller, browser-native)
#
#  Rebuild:
#    vhs scripts/demo/install.tape
# ─────────────────────────────────────────────────────────────────────

Output docs/assets/install.gif
Output docs/assets/install.mp4
Output docs/assets/install.webm

# ── Canvas ─────────────────────────────────────────────────────────
# 1200x720 sits well in 2-col landing layouts and renders crisp on
# README. Generous padding so it feels like Bun / Astro / Charm demos.
Set Shell      "bash"
Set FontFamily "Geist Mono"
Set FontSize   17
Set LineHeight 1.4
Set Width      1200
Set Height     720
Set Padding    44
Set Margin     24
Set MarginFill "#050505"
Set BorderRadius 14

# ── Brand-matched theme ────────────────────────────────────────────
# Mirrors apps/marketing/styles/landing.css and the OG image
# generator: bg #0a0a0a, accent #10b981 (emerald), fg #fafafa.
Set Theme { "name": "Feedbot", "background": "#0a0a0a", "foreground": "#fafafa", "cursor": "#10b981", "selection": "#1f2937", "black": "#0a0a0a", "red": "#ef4444", "green": "#10b981", "yellow": "#f59e0b", "blue": "#3b82f6", "magenta": "#a855f7", "cyan": "#06b6d4", "white": "#fafafa", "brightBlack": "#525252", "brightRed": "#f87171", "brightGreen": "#34d399", "brightYellow": "#fbbf24", "brightBlue": "#60a5fa", "brightMagenta": "#c084fc", "brightCyan": "#22d3ee", "brightWhite": "#ffffff" }

# ── Hidden setup ───────────────────────────────────────────────────
# Branded prompt: a single emerald `$ ` glyph. Then neutralise the
# curl pipeline: aliasing `curl` to `:` (the no-op builtin) means the
# viewer-facing `curl ... | sh` line will type, run, and harmlessly
# do nothing — no network, no real curl invocation. The player kicks
# off after a brief beat that mimics curl resolving DNS.
Hide
Type `export PS1=$'\E[38;2;16;185;129m$\E[0m ' PS2='' PROMPT_COMMAND=''`
Enter
Type "alias curl=: sh=:"
Enter
Type "clear"
Enter
Sleep 200ms
Show

# ── Scene 1 — the one-liner ────────────────────────────────────────
# Viewer sees the canonical install command being typed live, exactly
# as if pasted into a fresh terminal.
Sleep 1s
Type "curl -fsSL https://get.feedbot.dev | sh"
Sleep 700ms
Enter
# Brief beat — feels like curl resolving / TLS handshake.
Sleep 900ms

# ── Scene 2 — the install ──────────────────────────────────────────
# Hide the bootstrap line; the player's own `clear` wipes the screen
# and the Feedbot banner is the next thing the viewer sees, exactly
# as the real installer would render.
Hide
Type "bash scripts/demo/install-demo.sh"
Enter
Sleep 600ms
Show

# Player runtime ≈ 24s. Hold an extra 3s on the success summary so
# paused viewers / GIF loops land on the green "Feedbot is running"
# line, not on a returning prompt.
Sleep 27s
