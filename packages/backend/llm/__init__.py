"""
LLM provider factory.

Configure via environment variables:
    LLM_PROVIDER  – "ollama" (default)
    OLLAMA_MODEL  – model name  (default "qwen2.5:7b")
    OLLAMA_HOST   – server URL  (default "http://localhost:11434")
"""

import os
from .base import LLMProvider


def get_provider() -> LLMProvider | None:
    """Return the configured LLM provider, or None if misconfigured."""
    name = os.environ.get("LLM_PROVIDER", "ollama")

    if name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(
            model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
            host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        )

    return None
