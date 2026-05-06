"""Anthropic provider — Structured Outputs via the official SDK's `parse()` method.

Reference: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
"""

from __future__ import annotations

import time
from typing import ClassVar

from anthropic import AsyncAnthropic

from feedbot_core.llm.base import Usage, register
from feedbot_core.llm.exceptions import LLMError, LLMRefusalError
from feedbot_core.llm.schema import Classification


@register("anthropic")
class AnthropicProvider:
    name: ClassVar[str] = "anthropic"
    default_model: ClassVar[str] = "claude-haiku-4-5"
    available_models: ClassVar[tuple[str, ...]] = (
        "claude-haiku-4-5",
        "claude-sonnet-4-6",
        "claude-opus-4-7",
    )

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model or self.default_model

    async def classify(self, *, text: str, project_hint: str = "") -> tuple[Classification, Usage]:
        system = (
            "You classify product-feedback messages from end users. "
            "Return a strict JSON object matching the schema. "
            "Be concise and conservative; do not invent fields."
        )
        if project_hint:
            system += f"\nThe project context: {project_hint}"

        t0 = time.perf_counter()
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": text}],
                output_format=Classification,
            )
        except Exception as exc:
            raise LLMError(f"anthropic call failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if getattr(response, "stop_reason", None) == "refusal":
            raise LLMRefusalError("anthropic refused to produce structured output")

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LLMError("anthropic returned no parsed_output")

        usage = Usage(
            input_tokens=getattr(response.usage, "input_tokens", 0) if response.usage else 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) if response.usage else 0,
            latency_ms=latency_ms,
        )
        return parsed, usage
