"""Pluggable email delivery.

Two backends:
  - `console` — prints to stdout. Use only in dev. The app refuses to issue
    magic links to public HTTPS deployments while this backend is selected.
  - `smtp`    — real SMTP (TLS). Required for production.

Selection is driven by the `EMAIL_BACKEND` env var. SMTP credentials are
read at module-import time but only validated on first send.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

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


def is_console_backend_unsafe_for_prod() -> bool:
    """True if EMAIL_BACKEND=console AND FEEDBOT_BASE_URL is https — i.e. unsafe."""
    backend = os.getenv("EMAIL_BACKEND", "console").lower().strip()
    base = os.getenv("FEEDBOT_BASE_URL", "").lower()
    return backend == "console" and base.startswith("https://")
