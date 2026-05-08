"""Backup primitives — ``pg_dump`` + tarball wrapping ``.env``.

A backup is a single ``feedbot-<UTC ISO>.tar.gz`` containing:

  - ``db.sql`` — output of ``pg_dump -Fc`` against the running
    ``db`` service (Postgres custom-format, restorable with
    ``pg_restore``).
  - ``.env``    — the operator's current env file, so a restore
    can recreate the same encryption key + DB credentials.
    Plaintext credentials live here so the file is mode 0600
    and the SPA only ever serves it over an authenticated owner
    session (never indexed publicly by Caddy).

We invoke ``docker compose exec`` against the db service rather
than connecting from Python: the postgres user already has
``pg_dump`` on its PATH and the container's IPC keeps the dump
off the host filesystem until we write the tarball atomically.

This module exposes pure functions: routers compose them, the
``Orchestrator`` facade stays thin.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("feedbot.orchestrator.backup")


# Where backups live, relative to the deployment's workdir. Single
# directory so ``ls`` and the SPA's listing endpoint match.
_BACKUPS_SUBDIR = "backups"

# Default container + binary names. Override via env vars only for
# tests; production uses the compose-assigned names.
_DB_SERVICE = os.getenv("FEEDBOT_BACKUP_DB_SERVICE", "db")
_DB_USER = os.getenv("FEEDBOT_BACKUP_DB_USER", "feedbot")
_DB_NAME = os.getenv("FEEDBOT_BACKUP_DB_NAME", "feedbot")

# How long we wait for ``pg_dump`` before giving up. Generous because
# small DBs return in under a second but a multi-GB instance can
# take minutes.
_DUMP_TIMEOUT_S = 600


def _workdir() -> Path:
    return Path(os.getenv("FEEDBOT_WORKDIR") or os.getcwd())


def _backups_dir() -> Path:
    """Resolve and ensure the backups directory exists.

    Tests can override the parent via ``FEEDBOT_BACKUPS_DIR``.
    """
    override = os.getenv("FEEDBOT_BACKUPS_DIR")
    path = Path(override) if override else _workdir() / _BACKUPS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """One row of the backups directory listing."""

    filename: str
    path: Path
    size_bytes: int
    created_at: datetime


class BackupError(RuntimeError):
    """Raised when ``pg_dump`` or tar construction fails."""


def list_backups() -> list[BackupRecord]:
    """Return ``feedbot-*.tar.gz`` files in the backups dir.

    Sorted newest first by mtime. Files that don't match the
    expected name pattern are ignored — operators sometimes drop
    pre-existing dumps in the same directory and we don't want to
    surface those as if Feedbot had created them.
    """
    out: list[BackupRecord] = []
    for p in _backups_dir().iterdir():
        if not p.is_file():
            continue
        if not (p.name.startswith("feedbot-") and p.name.endswith(".tar.gz")):
            continue
        try:
            stat = p.stat()
        except FileNotFoundError:  # pragma: no cover — race
            continue
        out.append(
            BackupRecord(
                filename=p.name,
                path=p,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            )
        )
    out.sort(key=lambda b: b.created_at, reverse=True)
    return out


def get_backup(filename: str) -> BackupRecord | None:
    """Look up a single backup by filename.

    Refuses anything containing path separators so the download
    endpoint can't be tricked into ``../../etc/passwd``.
    """
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    if not (filename.startswith("feedbot-") and filename.endswith(".tar.gz")):
        return None
    target = _backups_dir() / filename
    if not target.exists() or not target.is_file():
        return None
    stat = target.stat()
    return BackupRecord(
        filename=filename,
        path=target,
        size_bytes=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def _binary() -> str:
    return os.getenv("FEEDBOT_DOCKER_BIN") or shutil.which("docker") or "docker"


def _project_name() -> str:
    return os.getenv("FEEDBOT_COMPOSE_PROJECT", "feedbot")


async def _pg_dump_to_file(target: Path) -> None:
    """Stream ``pg_dump -Fc`` from the db service to ``target``.

    Runs ``docker compose -p <project> exec -T <db> pg_dump ...``
    with stdout redirected to ``target`` via the subprocess pipe —
    this avoids a temp file inside the db container and keeps the
    dump on the host filesystem the orchestrator manages.
    """
    cmd = [
        _binary(),
        "compose",
        "-p",
        _project_name(),
        "exec",
        "-T",  # disable TTY so docker doesn't try to allocate one
        _DB_SERVICE,
        "pg_dump",
        "-U",
        _DB_USER,
        "-Fc",  # custom format, restorable with pg_restore
        _DB_NAME,
    ]
    log.info("orchestrator.backup: %s", " ".join([*cmd[:6], "…"]))
    with target.open("wb") as out_fd:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(_workdir()),
            stdout=out_fd,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=_DUMP_TIMEOUT_S
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise BackupError(
                f"pg_dump timed out after {_DUMP_TIMEOUT_S}s"
            ) from None

    if proc.returncode != 0:
        stderr = (stderr_b or b"").decode(errors="replace").strip()
        raise BackupError(f"pg_dump exited {proc.returncode}: {stderr}")


def _env_path() -> Path:
    """Resolve the operator's ``.env`` to bundle into the tarball."""
    override = os.getenv("FEEDBOT_ENV_FILE")
    if override:
        return Path(override)
    return _workdir() / ".env"


async def create_backup() -> BackupRecord:
    """Run ``pg_dump`` + tar a fresh archive. Returns the record.

    Atomic: writes everything to a tmp file in the same directory
    and renames at the end, so a partial run never appears in
    ``list_backups()``.
    """
    backups_dir = _backups_dir()
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    final_name = f"feedbot-{timestamp}.tar.gz"
    final_path = backups_dir / final_name

    # Stage the dump + tarball in a tmp working dir; only the final
    # ``os.replace`` makes it visible to ``list_backups``.
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=str(backups_dir)) as tmpdir:
        tmp = Path(tmpdir)
        dump_path = tmp / "db.sql"
        await _pg_dump_to_file(dump_path)

        # ``.env`` is best-effort: a fresh install may not have one
        # at the host path yet (the operator hasn't saved any
        # settings via the UI). Skip silently.
        env_path = _env_path()

        tarball_tmp = tmp / final_name
        with tarfile.open(tarball_tmp, "w:gz") as tf:
            tf.add(dump_path, arcname="db.sql")
            if env_path.exists():
                tf.add(env_path, arcname=".env")

        os.chmod(tarball_tmp, 0o600)
        os.replace(tarball_tmp, final_path)

    stat = final_path.stat()
    return BackupRecord(
        filename=final_name,
        path=final_path,
        size_bytes=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )
