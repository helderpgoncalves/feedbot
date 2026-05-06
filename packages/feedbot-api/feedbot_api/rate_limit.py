"""Process-local rate limiter via slowapi.

Single-process is fine for our deployment story (one Coolify api replica).
If we scale out we'll swap the in-memory store for Redis — slowapi supports
both via the storage_uri argument.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
