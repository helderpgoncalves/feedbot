"""Importing this package triggers each provider module to register itself.

To add a new provider:
    1. Drop a new module under this directory (e.g. `gemini.py`).
    2. In that module, import `register` from feedbot_core.llm.base and decorate
       a class implementing ProviderProtocol.
    3. Add the import below.
"""

from feedbot_core.llm.providers import anthropic, openai

__all__ = ["anthropic", "openai"]
