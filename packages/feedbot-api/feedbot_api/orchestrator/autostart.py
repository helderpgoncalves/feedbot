"""Autostart writers — systemd on Linux, launchd on macOS.

Writes a unit file that calls ``docker compose up -d`` from the
deployment's working directory at boot. Disabling reverses both the
service registration and the file. We deliberately keep this tiny:
the unit only does ``compose up -d``; long-running supervision is
Docker's job (each service has ``restart: unless-stopped``).

For Linux without systemd we don't try to be clever — we return a
``ManualSetupRequired`` payload with copy-paste instructions and let
the UI render them. OpenRC / runit / sysvinit users can wire it up
themselves; the population is small enough that we shouldn't pretend
to support it untested.
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

log = logging.getLogger("feedbot.orchestrator.autostart")


class Platform(StrEnum):
    LINUX_SYSTEMD = "linux-systemd"
    LINUX_OTHER = "linux-other"
    MACOS_LAUNCHD = "macos-launchd"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AutostartStatus:
    platform: Platform
    enabled: bool
    unit_path: str | None
    manual_instructions: str | None = None


def _detect_platform() -> Platform:
    system = platform.system()
    if system == "Darwin":
        return Platform.MACOS_LAUNCHD
    if system == "Linux":
        # ``/run/systemd/system`` exists when systemd is PID 1.
        if Path("/run/systemd/system").is_dir():
            return Platform.LINUX_SYSTEMD
        return Platform.LINUX_OTHER
    return Platform.UNKNOWN


def _workdir() -> Path:
    return Path(os.getenv("FEEDBOT_WORKDIR") or os.getcwd())


def _docker_bin() -> str:
    return os.getenv("FEEDBOT_DOCKER_BIN") or shutil.which("docker") or "/usr/bin/docker"


# ── Path resolution ─────────────────────────────────────────────────


def _systemd_unit_path() -> Path:
    """System-wide unit when running as root, user unit otherwise.

    ``XDG_CONFIG_HOME`` is honoured for the user case (matches
    ``systemctl --user``'s search path).
    """
    if os.geteuid() == 0:
        return Path("/etc/systemd/system/feedbot.service")
    base = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user" / "feedbot.service"


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "dev.feedbot.feedbot.plist"


# ── Unit file bodies ────────────────────────────────────────────────


def _systemd_unit_body() -> str:
    workdir = _workdir()
    docker = _docker_bin()
    return (
        "[Unit]\n"
        "Description=Feedbot self-host stack\n"
        "Requires=docker.service\n"
        "After=docker.service network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        f"WorkingDirectory={workdir}\n"
        f"ExecStart={docker} compose up -d\n"
        f"ExecStop={docker} compose down\n"
        "TimeoutStartSec=300\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _launchd_plist_body() -> str:
    workdir = _workdir()
    docker = _docker_bin()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>dev.feedbot.feedbot</string>
    <key>WorkingDirectory</key>
    <string>{workdir}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{docker}</string>
        <string>compose</string>
        <string>up</string>
        <string>-d</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{workdir}/logs/feedbot.autostart.log</string>
    <key>StandardErrorPath</key>
    <string>{workdir}/logs/feedbot.autostart.log</string>
</dict>
</plist>
"""


def _manual_instructions() -> str:
    workdir = _workdir()
    docker = _docker_bin()
    return (
        "Autostart on this Linux distro requires manual setup. To start\n"
        "Feedbot at boot, add an init script that runs:\n\n"
        f"    cd {workdir} && {docker} compose up -d\n\n"
        "Examples for OpenRC, runit, and supervisord live in docs/AUTOSTART.md."
    )


# ── Subprocess helpers ──────────────────────────────────────────────


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a small synchronous command (systemctl / launchctl).

    These tools complete in milliseconds and we already hold an
    HTTP request when called, so blocking briefly is fine — keeps
    error handling straightforward.
    """
    log.info("orchestrator.autostart: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _systemctl_args(extra: list[str]) -> list[str]:
    """``systemctl`` invocation tuned for system or user scope."""
    base = ["systemctl"]
    if os.geteuid() != 0:
        base.append("--user")
    return base + extra


# ── Public API ──────────────────────────────────────────────────────


def detect() -> Platform:
    return _detect_platform()


def status() -> AutostartStatus:
    plat = _detect_platform()
    if plat is Platform.LINUX_SYSTEMD:
        path = _systemd_unit_path()
        return AutostartStatus(
            platform=plat,
            enabled=path.exists(),
            unit_path=str(path),
        )
    if plat is Platform.MACOS_LAUNCHD:
        path = _launchd_plist_path()
        return AutostartStatus(
            platform=plat,
            enabled=path.exists(),
            unit_path=str(path),
        )
    if plat is Platform.LINUX_OTHER:
        return AutostartStatus(
            platform=plat,
            enabled=False,
            unit_path=None,
            manual_instructions=_manual_instructions(),
        )
    return AutostartStatus(
        platform=Platform.UNKNOWN,
        enabled=False,
        unit_path=None,
        manual_instructions=_manual_instructions(),
    )


class AutostartError(RuntimeError):
    """Raised when systemctl / launchctl rejects an enable/disable."""


def enable() -> AutostartStatus:
    plat = _detect_platform()
    if plat is Platform.LINUX_SYSTEMD:
        path = _systemd_unit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_systemd_unit_body(), encoding="utf-8")
        path.chmod(0o644)

        daemon_reload = _run(_systemctl_args(["daemon-reload"]))
        if daemon_reload.returncode != 0:
            raise AutostartError(
                f"systemctl daemon-reload failed: {daemon_reload.stderr.strip()}"
            )
        enable_cmd = _run(_systemctl_args(["enable", "feedbot.service"]))
        if enable_cmd.returncode != 0:
            raise AutostartError(
                f"systemctl enable failed: {enable_cmd.stderr.strip()}"
            )
        return status()

    if plat is Platform.MACOS_LAUNCHD:
        path = _launchd_plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_launchd_plist_body(), encoding="utf-8")
        path.chmod(0o644)

        load_cmd = _run(["launchctl", "load", "-w", str(path)])
        if load_cmd.returncode != 0:
            raise AutostartError(
                f"launchctl load failed: {load_cmd.stderr.strip()}"
            )
        return status()

    # Linux without systemd / unknown OS — return manual instructions.
    return status()


def disable() -> AutostartStatus:
    plat = _detect_platform()
    if plat is Platform.LINUX_SYSTEMD:
        # ``disable`` is fine even if the unit was never enabled, but
        # surface unexpected failures so we don't lie about the state.
        disable_cmd = _run(_systemctl_args(["disable", "feedbot.service"]))
        if disable_cmd.returncode != 0:
            log.warning(
                "systemctl disable returned %s: %s",
                disable_cmd.returncode,
                disable_cmd.stderr.strip(),
            )
        path = _systemd_unit_path()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        _run(_systemctl_args(["daemon-reload"]))
        return status()

    if plat is Platform.MACOS_LAUNCHD:
        path = _launchd_plist_path()
        if path.exists():
            unload = _run(["launchctl", "unload", "-w", str(path)])
            if unload.returncode != 0:
                log.warning(
                    "launchctl unload returned %s: %s",
                    unload.returncode,
                    unload.stderr.strip(),
                )
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        return status()

    return status()
