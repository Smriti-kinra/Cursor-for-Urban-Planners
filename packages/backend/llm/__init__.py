"""
LLM provider factory.

Set LLM_PROVIDER in .env to one of: ollama, groq, openai, gemini, anthropic
Each provider reads its own env vars for API key and model name.
"""

import os
from .base import LLMProvider


def get_provider() -> LLMProvider | None:
    """Return the configured LLM provider, or None if misconfigured."""
    name = os.environ.get("LLM_PROVIDER", "openai")

    if name == "openai":
        from .openai_provider import OpenAIProvider
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return None
        return OpenAIProvider(
            model=os.environ.get("OPENAI_MODEL", "gpt-5.4-nano"),
            api_key=api_key,
        )

    if name == "gemini":
        from .gemini_provider import GeminiProvider
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return None
        return GeminiProvider(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            api_key=api_key,
        )

    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        return AnthropicProvider(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            api_key=api_key,
        )

    return None
