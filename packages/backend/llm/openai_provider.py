"""
OpenAI provider — ChatGPT models (GPT-4o, GPT-4o-mini, etc.).

Get a key at https://platform.openai.com/api-keys
"""

from openai import AsyncOpenAI
from .openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    provider_name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", api_key: str = ""):
        super().__init__(model, AsyncOpenAI(api_key=api_key))
