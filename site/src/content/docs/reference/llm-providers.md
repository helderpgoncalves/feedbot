---
title: LLM providers
description: How Feedbot's LLM auto-triage works, how to configure OpenAI or Anthropic, and how to add a new provider.
---

Every inbound feedback can be auto-filled with `type`, `severity`, `summary`, `tags`, `language`, `sentiment` using **structured outputs** from OpenAI or Anthropic. Configured per project, with Fernet-encrypted keys at rest, monthly budget caps, and a full audit trail.

## Turning it on

1. Dashboard → project page → **LLM settings** (admin only).
2. Pick a provider (`openai` or `anthropic`), pick a model from the hint.
3. Paste the API key. It's encrypted at rest and never re-rendered in the UI.
4. (Optional) Set `monthly_budget_usd` — once the running total hits this cap, classification stops until the next calendar month.
5. Toggle **Enabled** → Save.
6. Click **Test connection**. The page reloads with `last_test_ok` (green) or `last_test_error` (red), plus a row in the recent-calls table.

Send a new feedback and check the row's `type` / `severity` / `tags` — they should be filled in.

:::caution
If the LLM fails for any reason (bad key, rate-limited, timeout), the failure is recorded in `llm_calls` but ingest **continues** with the fields the client sent. Classification is best-effort and never blocks ingest.
:::

## What it fills in

The classification schema (`feedbot_core/llm/schema.py`):

| Field | Type | Notes |
|---|---|---|
| `type` | `bug \| feature \| question \| praise \| other` | Best-guess from body. |
| `severity` | `low \| medium \| high \| critical` | Heuristic — confirm before paging anyone. |
| `summary` | string | One-sentence rephrase. |
| `tags` | list[string] | Free-form. Useful for grouping. |
| `language` | ISO-639-1 string | The language the feedback was written in. |
| `sentiment` | `positive \| neutral \| negative` | Coarse. |

## Cost tracking

Every call writes a row to `llm_calls`:

| Column | What |
|---|---|
| `provider`, `model` | Which one was called |
| `purpose` | `classify` / `test` / `request_more_info` |
| `input_tokens`, `output_tokens` | From the provider response |
| `usd_cost` | Computed server-side from `feedbot_core/llm/pricing.py` |
| `latency_ms` | End-to-end |
| `status` | `ok` / `error` / `over_budget` / `disabled` |
| `feedback_id` | Nullable, links to the feedback this call was for |
| `error_text` | Truncated provider error if `status=error` |

The settings page shows month-to-date spend and the last 50 calls. Pricing is computed server-side so historical cost survives provider price changes.

## Adding a new provider

The provider system is a registry. Adding Gemini, Groq, Mistral, or Ollama is **one new file**:

```python
# packages/feedbot-core/feedbot_core/llm/providers/gemini.py
from feedbot_core.llm.base import register, ProviderProtocol
from feedbot_core.llm.schema import Classification

@register("gemini")
class GeminiProvider:
    name = "gemini"
    default_model = "gemini-2.0-flash"
    available_models = ("gemini-2.0-flash", "gemini-1.5-pro")

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or self.default_model

    async def classify(self, *, text: str, project_hint: str = "") -> tuple[Classification, "Usage"]:
        # call the SDK, parse structured output, return (classification, usage)
        ...
```

…and one line in `providers/__init__.py` to import it. The settings UI dropdown reads `list_providers()` and picks it up automatically — no UI changes needed.

Add the model's pricing to `feedbot_core/llm/pricing.py` so cost is computed correctly:

```python
PRICING = {
    ("gemini", "gemini-2.0-flash"): (0.10, 0.40),  # ($/1M input, $/1M output)
    # ...
}
```

## Why structured outputs (and not JSON mode)?

Structured outputs guarantee the response matches the Pydantic schema — no parsing, no retry on malformed JSON, no field type coercion. Both providers support it natively:

- OpenAI: `client.chat.completions.parse(response_format=Classification)` — [docs](https://developers.openai.com/api/docs/guides/structured-outputs).
- Anthropic: `client.messages.parse(output_format=Classification)` — [docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

Providers that don't support structured outputs natively (Ollama for some models, smaller open-source models) can still be wired in with a JSON-mode fallback in their `classify()` method, but reliability is on you.
