"""Provider-agnostic tool declaration shared across MCP servers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolDeclaration:
    """A tool the LLM can call — pure JSON Schema, no provider lock-in."""
    name: str
    description: str
    parameters: dict  # standard JSON Schema object
