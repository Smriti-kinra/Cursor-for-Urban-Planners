"""
MCP (Model Context Protocol) Manager

Manages tool servers that provide additional capabilities to the AI.
Each server exposes tools as provider-agnostic ToolDeclarations and
handles execution of those tools.

Servers implemented:
  - osm: OpenStreetMap / Overpass API queries
  - weather: Open-Meteo weather + air quality
  - gis: Spatial analysis via Shapely (buffer, intersection, centroid, etc.)
"""

from __future__ import annotations

from typing import Any
from llm.base import ToolDeclaration

from .osm_server import OSMServer
from .weather_server import WeatherServer
from .gis_server import GISServer


class MCPManager:
    """Registry of MCP-style tool servers."""

    def __init__(self):
        self.servers: dict[str, Any] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.servers["osm"] = OSMServer()
        self.servers["weather"] = WeatherServer()
        self.servers["gis"] = GISServer()

    def get_tool_declarations(self) -> list[ToolDeclaration]:
        """Collect tool declarations from all registered servers."""
        declarations: list[ToolDeclaration] = []
        for server in self.servers.values():
            declarations.extend(server.get_declarations())
        return declarations

    def owns_tool(self, tool_name: str) -> bool:
        for server in self.servers.values():
            if tool_name in server.tool_names:
                return True
        return False

    async def execute(self, tool_name: str, args: dict) -> dict:
        for server in self.servers.values():
            if tool_name in server.tool_names:
                return await server.execute(tool_name, args)
        return {"error": f"No MCP server handles tool '{tool_name}'"}

    def list_servers(self) -> list[dict]:
        return [
            {
                "name": name,
                "tools": server.tool_names,
                "description": server.description,
            }
            for name, server in self.servers.items()
        ]
