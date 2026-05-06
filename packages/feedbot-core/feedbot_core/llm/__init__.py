"""LLM provider abstraction with structured outputs, cost tracking, and a
plug-in registry. Adding a new provider is a one-class change in `providers/`.

Public surface:
    Classification           — provider-agnostic Pydantic schema
    classify_feedback(...)   — high-level: takes settings, returns Classification
    ProviderProtocol         — what a provider must implement
    register, get_provider   — registry decorator + lookup
    list_providers           — for the UI to render the dropdown
    estimate_cost            — pricing lookup
    encrypt_key, decrypt_key — Fernet over FEEDBOT_SECRET_KEY
"""

# Importing the providers package triggers each provider's @register call.
from feedbot_core.llm import providers  # noqa: F401
from feedbot_core.llm.base import (
    ProviderProtocol,
    get_provider,
    list_providers,
    register,
)
from feedbot_core.llm.classify import ClassifyOutcome, classify_feedback
from feedbot_core.llm.crypto import decrypt_key, encrypt_key
from feedbot_core.llm.exceptions import LLMConfigError, LLMError, LLMRefusalError
from feedbot_core.llm.pricing import estimate_cost
from feedbot_core.llm.schema import Classification

__all__ = [
    "Classification",
    "ClassifyOutcome",
    "LLMConfigError",
    "LLMError",
    "LLMRefusalError",
    "ProviderProtocol",
    "classify_feedback",
    "decrypt_key",
    "encrypt_key",
    "estimate_cost",
    "get_provider",
    "list_providers",
    "register",
]
