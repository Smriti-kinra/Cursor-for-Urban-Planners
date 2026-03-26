"""
Anthropic provider — Claude models (Claude 4 Sonnet, Haiku, Opus, etc.).

Get a key at https://console.anthropic.com/settings/keys
Requires the `anthropic` package.
"""

from __future__ import annotations

import json
import time
import anthropic

from .base import LLMProvider, LLMResponse, Message, ToolCall, ToolDeclaration
from .usage import UsageEvent, estimate_cost, log_usage


class AnthropicProvider(LLMProvider):

    provider_name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str = ""):
        self.model = model
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    # ── public API ──

    async def generate(self, messages, tools=None, system=None):
        ant_messages = self._build_messages(messages)

        kwargs: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": ant_messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [self._tool_to_anthropic(t) for t in tools]

        start = time.monotonic()
        response = await self.client.messages.create(**kwargs)
        elapsed = int((time.monotonic() - start) * 1000)

        self._track(response, elapsed, "generate")
        return self._parse(response)

    async def generate_text(self, prompt, system=None):
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        start = time.monotonic()
        response = await self.client.messages.create(**kwargs)
        elapsed = int((time.monotonic() - start) * 1000)

        self._track(response, elapsed, "generate_text")
        return "".join(b.text for b in response.content if b.type == "text") or ""

    # ── usage tracking ──

    def _track(self, response, latency_ms: int, method: str):
        try:
            usage = response.usage
            tokens_in = getattr(usage, "input_tokens", 0) or 0
            tokens_out = getattr(usage, "output_tokens", 0) or 0
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
    def _tool_to_anthropic(t: ToolDeclaration) -> dict:
        return {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }

    @staticmethod
    def _build_messages(messages: list[Message]) -> list[dict]:
        """Convert our Message list to Anthropic's format.

        Key differences from OpenAI:
        - Assistant tool calls are content blocks (type=tool_use), not a separate field.
        - Tool results are user-role messages with type=tool_result blocks.
        - Consecutive same-role messages must be merged.
        """
        result: list[dict] = []

        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                blocks: list[dict] = []
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.args,
                    })
                result.append({"role": "assistant", "content": blocks})

            elif msg.role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content or "",
                }
                if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                    result[-1]["content"].append(block)
                else:
                    result.append({"role": "user", "content": [block]})

            elif msg.role == "user":
                result.append({"role": "user", "content": msg.content or ""})

            elif msg.role == "assistant":
                result.append({"role": "assistant", "content": msg.content or ""})

        return result

    @staticmethod
    def _parse(response) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    args=args,
                ))

        content = "".join(text_parts) or None
        return LLMResponse(content=content, tool_calls=tool_calls)
