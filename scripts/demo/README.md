# Install demo — VHS recording

Faithful clone of `curl -fsSL https://get.feedbot.dev | sh` output, rendered
with [VHS](https://github.com/charmbracelet/vhs).

## Files

| File | Purpose |
|---|---|
| `install.tape` | VHS script. The recording recipe. |
| `install-demo.sh` | Faithful playback of `install.sh` stages 1–13. No real Docker calls — purely cosmetic, deterministic, ~24s runtime. |

## Outputs

Rendered into `docs/assets/`:

- `install.gif` — embedded in the project README (GitHub-renderable).
- `install.mp4` — landing page hero (autoplay-friendly).
- `install.webm` — landing page fallback (smaller, browser-native).

## Rebuild

```sh
brew install vhs                       # one-time
brew install --cask font-geist-mono    # one-time
vhs scripts/demo/install.tape
```

Render takes ~90s and produces all three artifacts.

## Design

- **Theme** — Brand-matched: bg `#0a0a0a`, accent `#10b981` (emerald),
  fg `#fafafa`. Mirrors `apps/marketing/styles/landing.css`.
- **Font** — Geist Mono (matches the marketing site's `Geist Mono` body).
- **Canvas** — 1200×720 with 44px padding, 14px border radius, dark margin
  fill so the asset embeds cleanly into both light and dark surfaces.
- **Pacing** — The player times its own sleeps; the tape just captures.
  Final summary holds for ~3s so paused viewers / GIF loops land on the
  green "Feedbot is running" line.

## Editing the install output

If `install.sh` adds or renames a stage, mirror the change in
`install-demo.sh` (it's a paced, color-faithful reproduction). Then
re-run `vhs scripts/demo/install.tape`.
