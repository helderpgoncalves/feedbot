"""OpenAI provider — Structured Outputs via the official SDK's `parse()` method.

Reference: https://developers.openai.com/api/docs/guides/structured-outputs
Models supported (Aug 2024+): gpt-4o-mini, gpt-4o, gpt-4.1-mini, gpt-4.1, ...
"""

from __future__ import annotations

import time
from typing import ClassVar

from openai import AsyncOpenAI

from feedbot_core.llm.base import Usage, register
from feedbot_core.llm.exceptions import LLMError, LLMRefusalError
from feedbot_core.llm.schema import Classification


@register("openai")
class OpenAIProvider:
    name: ClassVar[str] = "openai"
    default_model: ClassVar[str] = "gpt-4o-mini"
    available_models: ClassVar[tuple[str, ...]] = (
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-mini",
        "gpt-4.1",
    )

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model or self.default_model

    async def classify(self, *, text: str, project_hint: str = "") -> tuple[Classification, Usage]:
        system = (
            "You classify product-feedback messages from end users. "
            "Return a strict JSON object matching the provided schema. "
            "Be concise and conservative; do not invent fields."
        )
        if project_hint:
            system += f"\nThe project context: {project_hint}"

        t0 = time.perf_counter()
        try:
            completion = await self._client.chat.completions.parse(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                response_format=Classification,
            )
        except Exception as exc:
            raise LLMError(f"openai call failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - t0) * 1000)

        choice = completion.choices[0]
        if choice.message.refusal:
            raise LLMRefusalError(choice.message.refusal)
        if choice.message.parsed is None:
            raise LLMError("openai returned no parsed output and no refusal")

        usage = Usage(
            input_tokens=completion.usage.prompt_tokens if completion.usage else 0,
            output_tokens=completion.usage.completion_tokens if completion.usage else 0,
            latency_ms=latency_ms,
        )
        return choice.message.parsed, usage
