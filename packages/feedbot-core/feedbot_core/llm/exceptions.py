class LLMError(Exception):
    """Generic LLM call failure (network, API error, parsing)."""


class LLMRefusalError(LLMError):
    """The provider explicitly refused to produce the structured output."""


class LLMConfigError(LLMError):
    """Configuration is invalid (missing key, unknown provider, missing model)."""
