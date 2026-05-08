"""Update primitives — current version + GHCR check + apply.

The "Update now" UX is two endpoints:

  - ``check()`` — non-mutating. Compares the running build SHA
    against the newest tag on GHCR and returns
    ``UpdateInfo(current, latest, available)``. Network failures
    set ``error`` and leave ``available=False`` so the UI doesn't
    nag the operator over a transient hiccup.

  - ``apply()`` — wraps ``compose.pull`` + ``compose.up`` (which
    re-creates containers using the freshly-pulled images).
    Migrations run on the api container's boot command
    (``alembic upgrade head && uvicorn …``) so we don't need a
    separate migration step here.

GHCR tag listing is anonymous. The repo defaults to
``ghcr.io/feedbot/feedbot-api`` — operators on a private fork can
override via ``FEEDBOT_UPDATES_REPO`` (e.g. their own GHCR org).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger("feedbot.orchestrator.updates")


# Public GHCR repo we treat as the canonical source of truth. The
# images published by the I0 CI workflow live at this name.
_DEFAULT_REPO = "feedbot/feedbot-api"

# How long we wait for the GHCR API. Generous because the public
# token endpoint can be slow on cold starts; tight enough that the
# Settings page never feels hung.
_TIMEOUT_S = 10.0


def _repo() -> str:
    return os.getenv("FEEDBOT_UPDATES_REPO", _DEFAULT_REPO)


def current_version() -> str:
    """Best-effort version string for the running container.

    Mirrors the SPA footer + ``GET /v1/admin/system/status.version``
    so the operator sees the same value across surfaces.
    """
    return os.getenv("FEEDBOT_BUILD_SHA") or "dev"


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    current: str
    latest: str | None
    available: bool
    error: str | None = None


# ── GHCR tag discovery ──────────────────────────────────────────────


def _is_release_tag(tag: str) -> bool:
    """Filter out floating + sha-only tags from the version list.

    GHCR carries everything we push: ``latest``, ``main``,
    ``v1.2.3``, ``sha-abcdef0``. We only treat semver-shaped tags
    as comparable releases — anything else might just be a moving
    pointer or a CI artifact.
    """
    return bool(re.match(r"^v?\d+\.\d+\.\d+(?:[\w.+-]*)?$", tag))


def _semver_key(tag: str) -> tuple[int, ...]:
    """Sort key for release tags. Strips the leading ``v`` if any."""
    cleaned = tag.lstrip("v")
    parts = re.split(r"[^\d]+", cleaned)
    return tuple(int(p) if p.isdigit() else 0 for p in parts if p)


async def _fetch_anonymous_token(client: httpx.AsyncClient, repo: str) -> str:
    """GHCR's tag-list endpoint requires a Bearer token even for
    public images; the token endpoint hands one out anonymously.
    """
    url = f"https://ghcr.io/token?scope=repository:{repo}:pull"
    resp = await client.get(url)
    resp.raise_for_status()
    body = resp.json() or {}
    token = body.get("token")
    if not token:
        raise RuntimeError("GHCR token endpoint returned no token")
    return str(token)


async def _list_tags(repo: str) -> list[str]:
    """Return every tag GHCR currently has for ``repo``.

    Pagination: GHCR honours the standard Docker registry
    ``Link: <…>; rel="next"`` header. We iterate until the header
    is gone or we've collected an unreasonable number — 500 is
    the safety cap so a misconfigured registry can't make us
    scrape forever.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        token = await _fetch_anonymous_token(client, repo)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://ghcr.io/v2/{repo}/tags/list?n=100"
        out: list[str] = []
        for _ in range(10):
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json() or {}
            tags = body.get("tags") or []
            out.extend(tags)
            link = resp.headers.get("Link", "")
            if not link or "rel=\"next\"" not in link:
                break
            # ``Link: </v2/foo/tags/list?n=100&last=v1.2.3>; rel="next"``
            m = re.search(r"<([^>]+)>;\s*rel=\"next\"", link)
            if not m:
                break
            url = "https://ghcr.io" + m.group(1)
            if len(out) > 500:
                break
        return out


async def check() -> UpdateInfo:
    """Resolve the latest release tag and compare to the running version.

    Network and registry errors are surfaced as ``error`` rather
    than raising — the Settings page polls this routinely and
    operators don't want the UI to scream every time their ISP
    blips.
    """
    cur = current_version()
    repo = _repo()
    try:
        tags = await _list_tags(repo)
    except (httpx.HTTPError, RuntimeError) as exc:
        log.info("orchestrator.updates: GHCR check failed: %s", exc)
        return UpdateInfo(current=cur, latest=None, available=False, error=str(exc))

    releases = sorted(
        (t for t in tags if _is_release_tag(t)), key=_semver_key, reverse=True
    )
    if not releases:
        return UpdateInfo(
            current=cur,
            latest=None,
            available=False,
            error=f"no release tags on {repo}",
        )

    latest = releases[0]
    # ``cur`` is usually a 7-char SHA; the comparison only makes
    # sense when both sides are semver. Anything else falls back
    # to "available=True" so the operator at least sees the
    # button. They can opt out by ignoring it.
    available = (
        _semver_key(cur) < _semver_key(latest)
        if cur and _is_release_tag(cur)
        else True
    )
    return UpdateInfo(current=cur, latest=latest, available=available)
