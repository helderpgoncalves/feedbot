"""Docker Compose operations.

The API container mounts ``/var/run/docker.sock`` so it can drive
the host's Docker daemon directly. We invoke ``docker compose``
rather than the Python SDK because the project name + working
directory + ``.env`` resolution match exactly what the operator
ran by hand on first boot, and the binary handles dependency
ordering (``depends_on`` + healthchecks) for free.

Trade-off: the API has full Docker control. Mitigated by:
- ``require_owner`` on every endpoint that calls into here.
- All actions audited via ``orchestrator.audit``.
- Self-host only (cloud builds short-circuit at the router layer).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("feedbot.orchestrator.compose")


# Default compose project name. Matches ``name: feedbot`` at the top
# of ``docker-compose.yml``; can be overridden if a deployment runs
# multiple stacks side-by-side.
DEFAULT_PROJECT_NAME = "feedbot"

# Service names that the orchestrator knows about. Used as a guard
# so a typo doesn't try to restart ``"hax"`` and time out.
KNOWN_SERVICES: frozenset[str] = frozenset(
    {"caddy", "web", "api", "bot", "db"}
)

# How long we wait for ``docker compose`` to return before giving
# up. ``up -d`` and ``restart`` take seconds in practice but we
# allow generous headroom for slow disks / first-time pulls.
DEFAULT_TIMEOUT_S = 120


class ComposeError(RuntimeError):
    """Raised when a compose command fails."""

    def __init__(self, *, args: list[str], returncode: int, stderr: str):
        super().__init__(
            f"docker compose {' '.join(args)} exited {returncode}: {stderr.strip()}"
        )
        self.args_used = args
        self.returncode = returncode
        self.stderr = stderr


@dataclass(frozen=True, slots=True)
class ComposeResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def _workdir() -> Path:
    """Directory containing ``docker-compose.yml``.

    Defaults to ``FEEDBOT_WORKDIR`` (set by the installer / systemd
    unit). Falls back to the current working directory so dev runs
    from the repo root keep working.
    """
    return Path(os.getenv("FEEDBOT_WORKDIR") or os.getcwd())


def _project_name() -> str:
    return os.getenv("FEEDBOT_COMPOSE_PROJECT", DEFAULT_PROJECT_NAME)


def _binary() -> str:
    """Resolve the docker binary, honouring ``FEEDBOT_DOCKER_BIN``.

    Tests stub this with a fake script so we never actually shell out
    to the real daemon.
    """
    return os.getenv("FEEDBOT_DOCKER_BIN") or shutil.which("docker") or "docker"


async def _run(args: list[str], *, timeout: float = DEFAULT_TIMEOUT_S) -> ComposeResult:
    full = [_binary(), "compose", "-p", _project_name(), *args]
    log.info("orchestrator.compose: %s", " ".join(full))
    proc = await asyncio.create_subprocess_exec(
        *full,
        cwd=str(_workdir()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ComposeError(
            args=args,
            returncode=-1,
            stderr=f"timed out after {timeout}s",
        ) from None

    stdout = stdout_b.decode(errors="replace")
    stderr = stderr_b.decode(errors="replace")
    if proc.returncode != 0:
        raise ComposeError(
            args=args, returncode=proc.returncode or 1, stderr=stderr
        )
    return ComposeResult(
        args=args, returncode=0, stdout=stdout, stderr=stderr
    )


def _validate_service(service: str) -> None:
    if service not in KNOWN_SERVICES:
        raise ValueError(
            f"unknown compose service {service!r}; "
            f"allowed: {sorted(KNOWN_SERVICES)}"
        )


async def restart(service: str | None = None) -> ComposeResult:
    """Restart one service or the whole stack.

    Restart re-reads ``.env`` for the targeted services without
    pulling new images — exactly what we want after rewriting an
    SMTP password.
    """
    if service is None:
        return await _run(["restart"])
    _validate_service(service)
    return await _run(["restart", service])


async def up(service: str | None = None, *, profiles: list[str] | None = None) -> ComposeResult:
    """Start the stack (or one service) with detached mode.

    ``up -d`` is idempotent: already-running services with no spec
    change are left alone. Profiles let us start the bot service,
    which is opt-in (``profiles: ["bot"]`` in compose).
    """
    args = ["up", "-d"]
    if profiles:
        # Profiles must come *before* the subcommand on the docker
        # CLI; ``-p projectname`` and ``--profile`` both apply to
        # the top-level invocation.
        args = ["--profile", *profiles, "up", "-d"]
    if service is not None:
        _validate_service(service)
        args.append(service)
    return await _run(args)


async def stop(service: str) -> ComposeResult:
    """Stop a single service without removing it."""
    _validate_service(service)
    return await _run(["stop", service])


async def pull() -> ComposeResult:
    """Pull the latest image tags. Used by the upgrade flow."""
    return await _run(["pull"], timeout=600)


async def ps() -> ComposeResult:
    """Compact JSON view of running services."""
    return await _run(["ps", "--format", "json"], timeout=15)
