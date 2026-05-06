"""Provider-agnostic schema for inbound feedback classification.

Both OpenAI and Anthropic structured outputs hand us back a Pydantic instance,
so the same model works for every provider. New providers just have to convert
their native response into this shape.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Classification(BaseModel):
    """The shape an LLM must produce when classifying a piece of feedback.

    Schema is intentionally narrow: provider-portable, no recursion, no nullable
    where avoidable. OpenAI/Anthropic strict modes both accept this verbatim.
    """

    type: Literal["bug", "feature", "question", "other"] = Field(description="What kind of feedback this is.")
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description=(
            "Severity from the team's perspective: critical = production broken, "
            "high = blocking many users, medium = workaround exists, low = nice-to-have."
        )
    )
    summary: str = Field(description="One-sentence summary in the user's original language. Max ~140 chars.")
    tags: list[str] = Field(
        default_factory=list,
        description="2-6 short keywords or area tags (e.g. 'export', 'ios', 'auth').",
    )
    language: str = Field(description="Detected language code (ISO 639-1, e.g. 'en', 'pt', 'fr').")
    sentiment: Literal["positive", "neutral", "negative"] = Field(description="Tone of the reporter's message.")
