"""Pluggable email delivery.

Two backends:
  - `console` — prints to stdout. Use only in dev. The app refuses to issue
    magic links to public HTTPS deployments while this backend is selected.
  - `smtp`    — real SMTP (TLS). Required for production.

Resolution precedence at every send:
  1. ``InstanceConfig`` row in the DB (admin panel) — preferred for self-host
     and any deployment where the operator wants to change SMTP without a
     redeploy.
  2. ``EMAIL_BACKEND`` + ``SMTP_*`` env vars — used as a fallback when the
     DB row is empty, and as an explicit override when the operator wants
     immutable secrets (Kubernetes, Coolify shared SMTP across tenants).

Routers should call :func:`resolve_email_backend(session)` for normal sends
and only fall back to :func:`email_backend_from_env` when no session is
available (rare — the bootstrap endpoint that runs *before* the DB has any
users still has a session, so that path uses the resolver too).
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("feedbot.email")


class EmailBackend(Protocol):
    name: str

    def send(self, *, to: str, subject: str, body: str) -> None: ...


class ConsoleBackend:
    name = "console"

    def send(self, *, to: str, subject: str, body: str) -> None:
        log.info("[email/console] to=%s subject=%s\n%s", to, subject, body)


class SMTPBackend:
    name = "smtp"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        starttls: bool = True,
    ):
        if not host or not sender:
            raise RuntimeError("SMTPBackend requires SMTP_HOST and SMTP_FROM")
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.starttls = starttls

    def send(self, *, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        ctx = ssl.create_default_context()
        if self.port == 465:  # implicit TLS
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=15) as s:
                if self.username:
                    s.login(self.username, self.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=15) as s:
                if self.starttls:
                    s.starttls(context=ctx)
                if self.username:
                    s.login(self.username, self.password)
                s.send_message(msg)
        log.info("[email/smtp] sent to=%s subject=%s", to, subject)


def email_backend_from_env() -> EmailBackend:
    """Build a backend purely from env. Use only when no DB session exists."""
    name = os.getenv("EMAIL_BACKEND", "console").lower().strip()
    if name == "smtp":
        return SMTPBackend(
            host=os.getenv("SMTP_HOST", ""),
            port=int(os.getenv("SMTP_PORT", "587")),
            username=os.getenv("SMTP_USER", ""),
            password=os.getenv("SMTP_PASSWORD", ""),
            sender=os.getenv("SMTP_FROM", ""),
            starttls=os.getenv("SMTP_PORT", "587") != "465",
        )
    return ConsoleBackend()


async def resolve_email_backend(session: AsyncSession) -> EmailBackend:
    """Pick the right backend, preferring DB-saved SMTP over env.

    Order:
      1. ``InstanceConfig`` row has a non-empty ``smtp_host`` → SMTPBackend
         built from those (decrypted) values.
      2. ``EMAIL_BACKEND=smtp`` + valid env → SMTPBackend from env.
      3. ConsoleBackend (logs the message — dev only).

    The DB lookup is one cheap query per send; magic-link issuance is rare
    enough that we don't bother caching. If you call this from a hot path,
    cache at the call site.
    """
    # Lazy import: orchestrator/settings.py pulls SQLAlchemy + crypto helpers,
    # so importing it at module load forces those onto every CLI script that
    # only needs the env-based backend.
    from feedbot_api.orchestrator import settings as orch_settings

    try:
        cfg = await orch_settings.load(session)
    except Exception as err:  # pragma: no cover — DB hiccup, not fatal
        log.warning("[email] DB lookup failed, falling back to env: %s", err)
        return email_backend_from_env()

    smtp = cfg.smtp
    if smtp.is_configured and smtp.sender:
        port = smtp.port or 587
        return SMTPBackend(
            host=smtp.host or "",
            port=port,
            username=smtp.user or "",
            password=smtp.password or "",
            sender=smtp.sender,
            starttls=port != 465,
        )

    return email_backend_from_env()


async def is_email_delivery_safe(session: AsyncSession) -> bool:
    """True when sending email is acceptable for the current deployment.

    Three-way decision:
      - SMTP backend resolves (env or DB) → True (real delivery).
      - Console backend AND ``FEEDBOT_BASE_URL`` is not HTTPS → True
        (dev/local — magic links go to logs and that's fine).
      - Console backend AND public HTTPS deployment → False (users would
        never receive the email; the caller should 503 or fall back to
        rendering the link inline).
    """
    backend = await resolve_email_backend(session)
    if backend.name == "smtp":
        return True
    base = os.getenv("FEEDBOT_BASE_URL", "").lower()
    return not base.startswith("https://")


def is_console_backend_unsafe_for_prod() -> bool:
    """True if env config alone would land us on console backend over HTTPS.

    Kept for callers that don't have a session (rare). Prefer
    :func:`is_email_delivery_safe` when you do — the env-only check returns
    True for a deployment that has SMTP saved in the DB but no env vars,
    which is a false positive and the most common production setup.
    """
    backend = os.getenv("EMAIL_BACKEND", "console").lower().strip()
    base = os.getenv("FEEDBOT_BASE_URL", "").lower()
    return backend == "console" and base.startswith("https://")
