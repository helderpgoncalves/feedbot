#!/bin/sh
# Build the static site for get.feedbot.dev. Coolify Static Site mode
# points at this directory; on each git push it re-runs this script
# and serves `dist/`.
#
# Layout produced:
#   dist/install.sh     The canonical installer (copied from repo root).
#   dist/index.html     A human-friendly explainer for browser visitors.
#
# In Coolify → Application → Custom nginx config (or Caddyfile),
# add a rewrite so `curl https://get.feedbot.dev | sh` (which fetches
# /) returns install.sh as text/plain rather than the index page.
# A copy-paste snippet is included in docs/DEPLOY-COOLIFY.md.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$(cd "$(dirname "$0")" && pwd)/dist"

rm -rf "$OUT"
mkdir -p "$OUT"

# 1. Copy the installer from the repo root.
cp "${REPO_ROOT}/install.sh" "${OUT}/install.sh"
chmod 0644 "${OUT}/install.sh"

# 2. Browser-facing explainer.
cat >"${OUT}/index.html" <<'HTML'
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Install Feedbot</title>
    <meta name="description" content="One-line installer for Feedbot — open-source feedback collection.">
    <style>
        :root { color-scheme: dark; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 720px;
            margin: 4rem auto;
            padding: 0 1.5rem;
            color: #f5f5f5;
            background: #0a0a0a;
            line-height: 1.6;
        }
        h1 { font-size: 1.75rem; margin-bottom: 0.5rem; }
        p.tagline { color: #a3a3a3; margin-top: 0; }
        pre, code {
            font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
        }
        pre {
            background: #171717;
            border: 1px solid #262626;
            padding: 1rem 1.25rem;
            border-radius: 8px;
            overflow-x: auto;
            font-size: 0.95rem;
        }
        code { color: #10b981; }
        a { color: #10b981; }
        a:hover { text-decoration: none; }
        .hint { color: #a3a3a3; font-size: 0.9rem; }
    </style>
</head>
<body>
    <h1>Install Feedbot</h1>
    <p class="tagline">One command to bootstrap a self-hosted Feedbot stack.</p>

    <pre><code>curl -fsSL https://get.feedbot.dev | sh</code></pre>

    <p class="hint">
        Want to read the script before piping it to a shell? Good instinct.
    </p>

    <pre><code>curl -fsSL https://get.feedbot.dev/install.sh &gt; install.sh
less install.sh
sh install.sh</code></pre>

    <p>
        Documentation:
        <a href="https://feedbot.dev/">feedbot.dev</a>
        ·
        <a href="https://feedbot.dev/quickstart-selfhost/">Quickstart</a>
        ·
        <a href="https://feedbot.dev/self-hosting/install/">Installer reference</a>
        ·
        <a href="https://github.com/helderpgoncalves/feedbot">GitHub</a>
    </p>
</body>
</html>
HTML

echo "Built installer-host:"
ls -la "$OUT"
