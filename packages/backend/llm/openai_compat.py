"""
Shared base for every provider that speaks the OpenAI chat-completions API.

Ollama, Groq, OpenAI, Gemini (and any future OpenAI-compatible endpoint)
inherit from this — only the constructor differs.
"""

from __future__ import annotations

import json
import time
import uuid

from openai import AsyncOpenAI

from .base import LLMProvider, LLMResponse, Message, ToolCall, ToolDeclaration
from .usage import UsageEvent, estimate_cost, log_usage


class OpenAICompatProvider(LLMProvider):
    """Concrete LLMProvider for any OpenAI-compatible endpoint."""

    provider_name: str = "openai"

    def __init__(self, model: str, client: AsyncOpenAI):
        self.model = model
        self.client = client

    # ── public API ──

    async def generate(self, messages, tools=None, system=None):
        oai_messages: list[dict] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        for msg in messages:
            oai_messages.extend(self._msg_to_openai(msg))

        kwargs: dict = {"model": self.model, "messages": oai_messages}
        if tools:
            kwargs["tools"] = [self._tool_to_openai(t) for t in tools]

        start = time.monotonic()
        response = await self.client.chat.completions.create(**kwargs)
        elapsed = int((time.monotonic() - start) * 1000)

        self._track(response, elapsed, "generate")
        return self._parse(response)

    async def generate_text(self, prompt, system=None):
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})

        start = time.monotonic()
        response = await self.client.chat.completions.create(
            model=self.model, messages=msgs,
        )
        elapsed = int((time.monotonic() - start) * 1000)

        self._track(response, elapsed, "generate_text")
        return response.choices[0].message.content or ""

    # ── usage tracking ──

    def _track(self, response, latency_ms: int, method: str):
        try:
            usage = response.usage
            tokens_in = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
            tokens_out = getattr(usage, "completion_tokens", 0) or 0 if usage else 0
            model = getattr(response, "model", self.model) or self.model
            log_usage(UsageEvent(
                provider=self.provider_name,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=estimate_cost(model, tokens_in, tokens_out),
                latency_ms=latency_ms,
                method=method,
            ))
        except Exception:
            pass

    # ── format converters ──

    @staticmethod
    def _tool_to_openai(t: ToolDeclaration) -> dict:
        return {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }

    @staticmethod
    def _msg_to_openai(msg: Message) -> list[dict]:
        if msg.role == "assistant" and msg.tool_calls:
            return [{
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args),
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }]
        if msg.role == "tool":
            return [{
                "role": "tool",
                "content": msg.content or "",
                "tool_call_id": msg.tool_call_id or "",
            }]
        return [{"role": msg.role, "content": msg.content or ""}]

    @staticmethod
    def _parse(response) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                raw = tc.function.arguments
                args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                tool_calls.append(ToolCall(
                    id=tc.id or uuid.uuid4().hex[:8],
                    name=tc.function.name,
                    args=args,
                ))
        return LLMResponse(content=msg.content or None, tool_calls=tool_calls)
