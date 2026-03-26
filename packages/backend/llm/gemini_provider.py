"""
Gemini provider — Google's models via their OpenAI-compatible endpoint.

Get a key at https://aistudio.google.com/apikey
"""

from openai import AsyncOpenAI
from .openai_compat import OpenAICompatProvider


class GeminiProvider(OpenAICompatProvider):
    provider_name = "gemini"

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str = ""):
        super().__init__(
            model,
            AsyncOpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=api_key,
            ),
        )
