"""Symmetric encryption for project API keys.

We derive a Fernet key from FEEDBOT_SECRET_KEY (the same env var used to sign
session cookies). This keeps secret management to one variable. Rotating
FEEDBOT_SECRET_KEY invalidates stored keys — owners must re-enter them.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from feedbot_core.llm.exceptions import LLMConfigError


def _fernet() -> Fernet:
    secret = os.getenv("FEEDBOT_SECRET_KEY", "")
    if not secret:
        raise LLMConfigError("FEEDBOT_SECRET_KEY is not set; cannot encrypt LLM keys")
    # Fernet wants 32 url-safe base64 bytes. We hash the raw secret so any string works.
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_key(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_key(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise LLMConfigError("stored LLM key cannot be decrypted — FEEDBOT_SECRET_KEY may have been rotated") from exc
