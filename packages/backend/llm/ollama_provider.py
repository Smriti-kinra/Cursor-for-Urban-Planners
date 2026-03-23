"""
Ollama provider — talks to a local Ollama instance via its OpenAI-compatible API.

Because we use the standard OpenAI client, the same class can point at any
OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, etc.) by changing host.
"""

from __future__ import annotations

import json
import uuid

from openai import AsyncOpenAI

from .base import LLMProvider, LLMResponse, Message, ToolCall, ToolDeclaration


class OllamaProvider(LLMProvider):

    def __init__(self, model: str = "qwen2.5:7b", host: str = "http://localhost:11434"):
        self.model = model
        self.client = AsyncOpenAI(base_url=f"{host}/v1", api_key="ollama")

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

        response = await self.client.chat.completions.create(**kwargs)
        return self._parse(response)

    async def generate_text(self, prompt, system=None):
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model, messages=msgs,
        )
        return response.choices[0].message.content or ""

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
