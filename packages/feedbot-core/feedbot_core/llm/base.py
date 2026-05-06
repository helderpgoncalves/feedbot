"""Provider Protocol + plug-in registry.

Adding a new provider:

    # feedbot_core/llm/providers/groq.py
    from feedbot_core.llm.base import register
    from feedbot_core.llm.schema import Classification

    @register("groq")
    class GroqProvider:
        name = "groq"
        default_model = "llama-3.3-70b-versatile"
        available_models = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")

        def __init__(self, api_key: str, model: str | None = None):
            self._client = ...  # SDK init
            self._model = model or self.default_model

        async def classify(self, *, text: str, project_hint: str = "") -> tuple[Classification, "Usage"]:
            ...

Then add it to `feedbot_core/llm/providers/__init__.py` so the registry picks it up.
That's it — no other file changes anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable

from feedbot_core.llm.exceptions import LLMConfigError
from feedbot_core.llm.schema import Classification


@dataclass(frozen=True, slots=True)
class Usage:
    """Token + latency report from a provider call. Cost is computed elsewhere."""

    input_tokens: int
    output_tokens: int
    latency_ms: int


@runtime_checkable
class ProviderProtocol(Protocol):
    name: ClassVar[str]
    default_model: ClassVar[str]
    available_models: ClassVar[tuple[str, ...]]

    def __init__(self, api_key: str, model: str | None = None) -> None: ...

    async def classify(self, *, text: str, project_hint: str = "") -> tuple[Classification, Usage]: ...


# ─── Registry ───────────────────────────────────────────────────────────────


_registry: dict[str, type] = {}


def register(name: str):
    """Decorator: register a provider class under `name` in the global registry."""

    def deco(cls):
        if name in _registry:
            raise RuntimeError(f"LLM provider already registered: {name}")
        _registry[name] = cls
        return cls

    return deco


def list_providers() -> dict[str, dict[str, object]]:
    """Render-friendly view of the registry. Used by the dashboard dropdown.

    Shape: {"openai": {"default_model": "gpt-4o-mini", "available_models": (...)}, ...}
    """
    return {
        name: {
            "default_model": cls.default_model,
            "available_models": list(cls.available_models),
        }
        for name, cls in sorted(_registry.items())
    }


def get_provider(name: str, api_key: str, model: str | None = None) -> ProviderProtocol:
    cls = _registry.get(name)
    if cls is None:
        raise LLMConfigError(f"unknown LLM provider: {name!r}. Available: {sorted(_registry)}")
    if model and model not in cls.available_models:
        # Don't reject — providers ship new models all the time. Just warn-via-comment.
        # The test endpoint will catch a truly invalid model.
        pass
    return cls(api_key=api_key, model=model)


__all__ = [
    "ProviderProtocol",
    "Usage",
    "get_provider",
    "list_providers",
    "register",
]
