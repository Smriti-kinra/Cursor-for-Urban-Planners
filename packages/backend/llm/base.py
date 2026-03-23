"""
LLM abstraction layer.

Defines provider-agnostic types and the abstract LLMProvider interface.
Swap providers (Ollama, OpenAI, Anthropic, etc.) without touching app logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolDeclaration:
    """A tool the LLM can call — pure JSON Schema, no provider lock-in."""
    name: str
    description: str
    parameters: dict  # standard JSON Schema object


@dataclass
class ToolCall:
    """A single function call returned by the LLM."""
    id: str
    name: str
    args: dict


@dataclass
class Message:
    """Provider-agnostic chat message."""
    role: str  # "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LLMResponse:
    """Standardised response from any provider."""
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    """Interface every LLM backend must implement."""

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolDeclaration] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        """Chat completion with optional tool calling."""
        ...

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system: str | None = None,
    ) -> str:
        """Simple single-turn text generation (no tools)."""
        ...
