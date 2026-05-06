"""USD pricing per 1M tokens, by provider/model.

Source of truth: each provider's official pricing page. Update when prices change;
historical `llm_calls.usd_cost` rows are preserved by computing cost server-side
at insert time, so price changes don't retroactively rewrite history.
"""

from __future__ import annotations

# (input_per_1M_usd, output_per_1M_usd)
PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "openai": {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
        "gpt-4.1-mini": (0.40, 1.60),
        "gpt-4.1": (2.00, 8.00),
    },
    "anthropic": {
        "claude-haiku-4-5": (1.00, 5.00),
        "claude-sonnet-4-6": (3.00, 15.00),
        "claude-opus-4-7": (15.00, 75.00),
    },
}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the USD cost for a single call. Returns 0.0 for unknown models
    rather than raising — we still want the call logged even if pricing is stale.
    """
    rates = PRICING.get(provider, {}).get(model)
    if rates is None:
        return 0.0
    in_rate, out_rate = rates
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
