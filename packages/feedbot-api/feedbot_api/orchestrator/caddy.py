"""Caddy Admin API client.

The standalone caddy container exposes the admin endpoint on port
2019, *bound to its loopback inside the container only*. From the
host or the public internet it is unreachable; only sibling
containers on the ``feedbot_net`` Docker network can talk to it.
The api container is one of those siblings, so we POST JSON config
directly — no Caddyfile rewrite + restart cycle needed, the daemon
reloads in-place.

We POST a full config blob to ``/load`` rather than patching with
``PATCH``, because the IP-only ↔ domain transition flips
``auto_https`` and changes the listener address; a single
declarative load is simpler to reason about and idempotent.

When the user adds a domain:
  1. UI sends domain + email → router validates → calls ``apply_domain``.
  2. We build a config that listens on :443 with TLS managed by Caddy
     (Let's Encrypt) and on :80 redirects to https://.
  3. Caddy starts the ACME flow asynchronously; the UI polls
     ``status`` until the cert is provisioned.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("feedbot.orchestrator.caddy")


# Where the caddy admin API lives, from the api container's
# perspective. ``caddy`` is the Docker DNS name for the proxy
# service; 2019 is Caddy's default admin port.
DEFAULT_ADMIN_URL = "http://caddy:2019"


def _admin_url() -> str:
    return os.getenv("FEEDBOT_CADDY_ADMIN_URL", DEFAULT_ADMIN_URL).rstrip("/")


class CaddyError(RuntimeError):
    """Raised when the admin API rejects a request."""


# ── Config builders ─────────────────────────────────────────────────

# Upstreams. The reverse proxy lives in the same Docker network so
# we can address peers by service name.
_API_UPSTREAM = "api:8000"
_WEB_UPSTREAM = "web:80"


def _routes() -> list[dict[str, Any]]:
    """Common route table — same as the Caddyfile, in JSON form.

    Order matters: more specific paths first, catch-all last.
    """
    return [
        # /api/* → strip prefix, forward to the API
        {
            "match": [{"path": ["/api/*", "/api"]}],
            "handle": [
                {
                    "handler": "rewrite",
                    "strip_path_prefix": "/api",
                },
                {
                    "handler": "reverse_proxy",
                    "upstreams": [{"dial": _API_UPSTREAM}],
                },
            ],
        },
        # /mcp, /mcp/* → API (path-preserving)
        {
            "match": [{"path": ["/mcp", "/mcp/*"]}],
            "handle": [
                {
                    "handler": "reverse_proxy",
                    "upstreams": [{"dial": _API_UPSTREAM}],
                }
            ],
        },
        # /healthz → API (top-level liveness probe)
        {
            "match": [{"path": ["/healthz"]}],
            "handle": [
                {
                    "handler": "reverse_proxy",
                    "upstreams": [{"dial": _API_UPSTREAM}],
                }
            ],
        },
        # everything else → SPA
        {
            "handle": [
                {
                    "handler": "reverse_proxy",
                    "upstreams": [{"dial": _WEB_UPSTREAM}],
                }
            ]
        },
    ]


def build_ip_only_config() -> dict[str, Any]:
    """Pre-domain config: HTTP only on :80, no TLS.

    Mirrors ``caddy/Caddyfile`` (the IP-only state). Used to reset
    the proxy when the user removes a domain.
    """
    return {
        "apps": {
            "http": {
                "servers": {
                    "feedbot": {
                        "listen": [":80"],
                        "automatic_https": {"disable": True},
                        "routes": _routes(),
                    }
                }
            }
        }
    }


def build_domain_config(*, domain: str, letsencrypt_email: str) -> dict[str, Any]:
    """HTTPS config: :443 with managed TLS, :80 redirects.

    Caddy auto-provisions a Let's Encrypt cert for ``domain``. The
    UI will poll ``status()`` until the cert lands; in the meantime
    the listener is up but TLS handshakes fail with the staging /
    self-signed default — that's expected.
    """
    if not domain or "://" in domain:
        raise ValueError(f"domain must be a hostname, got {domain!r}")
    if not letsencrypt_email or "@" not in letsencrypt_email:
        raise ValueError("letsencrypt_email must be a valid address")

    return {
        "apps": {
            "http": {
                "servers": {
                    "feedbot": {
                        "listen": [":443"],
                        "routes": [
                            {
                                "match": [{"host": [domain]}],
                                "handle": [
                                    {
                                        "handler": "subroute",
                                        "routes": _routes(),
                                    }
                                ],
                                "terminal": True,
                            }
                        ],
                    },
                    "redirect": {
                        "listen": [":80"],
                        "automatic_https": {"disable": True},
                        "routes": [
                            {
                                "handle": [
                                    {
                                        "handler": "static_response",
                                        "status_code": 308,
                                        "headers": {
                                            "Location": [f"https://{domain}{{http.request.uri}}"]
                                        },
                                    }
                                ]
                            }
                        ],
                    },
                }
            },
            "tls": {
                "automation": {
                    "policies": [
                        {
                            "subjects": [domain],
                            "issuers": [
                                {
                                    "module": "acme",
                                    "email": letsencrypt_email,
                                }
                            ],
                        }
                    ]
                }
            },
        }
    }


# ── HTTP plumbing ───────────────────────────────────────────────────


async def load_config(config: dict[str, Any], *, timeout: float = 10.0) -> None:
    """POST a full config blob to ``/load``.

    Caddy validates the blob and either swaps to it atomically or
    returns 400 with a JSON error. We translate non-2xx into
    ``CaddyError`` so callers get a typed failure they can audit.
    """
    url = f"{_admin_url()}/load"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, json=config)
        except httpx.HTTPError as exc:
            raise CaddyError(f"caddy admin API unreachable at {url}: {exc}") from exc

    if resp.status_code >= 300:
        raise CaddyError(
            f"caddy /load returned {resp.status_code}: {resp.text.strip()}"
        )
    log.info("orchestrator.caddy: loaded new config (%d bytes)", len(resp.request.content or b""))


async def get_config(*, timeout: float = 5.0) -> dict[str, Any]:
    """Read the currently-active config (used by status / debugging)."""
    url = f"{_admin_url()}/config/"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise CaddyError(f"caddy admin API unreachable at {url}: {exc}") from exc

    if resp.status_code >= 300:
        raise CaddyError(
            f"caddy /config returned {resp.status_code}: {resp.text.strip()}"
        )
    try:
        return resp.json() or {}
    except ValueError:
        return {}


async def apply_domain(*, domain: str, letsencrypt_email: str) -> None:
    """Convenience: build + load the domain config in one call."""
    await load_config(build_domain_config(domain=domain, letsencrypt_email=letsencrypt_email))


async def clear_domain() -> None:
    """Revert to IP-only mode."""
    await load_config(build_ip_only_config())


async def cert_status(domain: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Return Caddy's view of ``domain``'s TLS state.

    Best-effort: reads the live config and pulls the ``tls`` block.
    The UI uses this for the 3-state chip (idle / applying / error).
    """
    config = await get_config(timeout=timeout)
    tls = (config.get("apps") or {}).get("tls") or {}
    policies = (tls.get("automation") or {}).get("policies") or []
    matched = [p for p in policies if domain in (p.get("subjects") or [])]
    return {
        "domain": domain,
        "configured": bool(matched),
        "policy_count": len(policies),
    }
