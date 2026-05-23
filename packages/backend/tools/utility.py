"""
Utility tools — cross-cutting operations the LLM can call.

Mirrors the MCP server pattern in `mcp_servers/`: the class exposes
`tool_names`, `get_declarations()`, and `execute(name, args)`. Used by
`routers/chat.py` for search, geocoding, measurements, and artifact
storage.

`create_artifact` returns `{"status": "created", "id": <int>}`. It does NOT
fire the `refresh_artifacts` UI action — `chat.py` detects the tool name
itself and emits that side-effect after `execute()` returns.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import httpx

from llm.base import ToolDeclaration


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    dlon, dlat = math.radians(lon2 - lon1), math.radians(lat2 - lat1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _shoelace_area_m2(coords: list) -> float:
    n = len(coords)
    if n < 3:
        return 0.0
    R = 6371000.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        xi = math.radians(coords[i][0]) * R * math.cos(math.radians(coords[i][1]))
        yi = math.radians(coords[i][1]) * R
        xj = math.radians(coords[j][0]) * R * math.cos(math.radians(coords[j][1]))
        yj = math.radians(coords[j][1]) * R
        area += xi * yj - xj * yi
    return abs(area) / 2


class UtilityServer:
    description = "Cross-cutting utility tools (search, geocoding, measurements, artifacts)"
    tool_names = {"web_search", "geocode", "measure_distance", "measure_area", "create_artifact"}

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="web_search",
                description="Search the web for urban planning info, regulations, demographics",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
            ToolDeclaration(
                name="geocode",
                description="Convert an address or place name to geographic coordinates",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Address or place name"}},
                    "required": ["query"],
                },
            ),
            ToolDeclaration(
                name="measure_distance",
                description="Calculate the distance along a series of points (km, miles, meters)",
                parameters={
                    "type": "object",
                    "properties": {
                        "points": {
                            "type": "array",
                            "description": "Array of [longitude, latitude] pairs",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                    "required": ["points"],
                },
            ),
            ToolDeclaration(
                name="measure_area",
                description="Calculate the area of a polygon (m², hectares, km², acres)",
                parameters={
                    "type": "object",
                    "properties": {
                        "polygon": {
                            "type": "array",
                            "description": "Array of [longitude, latitude] pairs forming the polygon",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                    "required": ["polygon"],
                },
            ),
            ToolDeclaration(
                name="create_artifact",
                description="Save a note, analysis, or report as a project artifact",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "artifact_type": {"type": "string", "description": "note, analysis, report, or sketch"},
                    },
                    "required": ["title", "content", "artifact_type"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "web_search":
            return await self._web_search(args.get("query", ""))
        if tool_name == "geocode":
            return await self._geocode(args.get("query", ""))
        if tool_name == "measure_distance":
            return self._measure_distance(args.get("points", []))
        if tool_name == "measure_area":
            return self._measure_area(args.get("polygon", []))
        if tool_name == "create_artifact":
            return self._create_artifact(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _web_search(self, query: str) -> dict:
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
            return {
                "results": [
                    {"title": r.get("title", ""), "body": r.get("body", ""), "href": r.get("href", "")}
                    for r in results
                ]
            }
        except Exception as e:
            return {"error": str(e)}

    async def _geocode(self, query: str) -> dict:
        try:
            async with httpx.AsyncClient() as http:
                resp = await http.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": query, "format": "json", "limit": 5},
                    headers={"User-Agent": "CursorUrbanPlanners/1.0"},
                )
                results = resp.json()
                return {
                    "results": [
                        {"display_name": r.get("display_name", ""), "lat": r.get("lat"), "lon": r.get("lon")}
                        for r in results
                    ]
                }
        except Exception as e:
            return {"error": str(e)}

    def _measure_distance(self, points: list) -> dict:
        if len(points) < 2:
            return {"error": "Need at least 2 points"}
        total_km = sum(
            _haversine_km(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
            for i in range(len(points) - 1)
        )
        return {
            "distance_km": round(total_km, 4),
            "distance_miles": round(total_km * 0.621371, 4),
            "distance_meters": round(total_km * 1000, 1),
        }

    def _measure_area(self, polygon: list) -> dict:
        if len(polygon) < 3:
            return {"error": "Need at least 3 points"}
        area_m2 = _shoelace_area_m2(polygon)
        return {
            "area_m2": round(area_m2, 1),
            "area_hectares": round(area_m2 / 10000, 4),
            "area_km2": round(area_m2 / 1e6, 6),
            "area_acres": round(area_m2 / 4046.86, 4),
        }

    def _create_artifact(self, args: dict) -> dict:
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.execute(
                "INSERT INTO artifacts (title, content, artifact_type) VALUES (?, ?, ?)",
                (args.get("title", "Untitled"), args.get("content", ""), args.get("artifact_type", "note")),
            )
            conn.commit()
            artifact_id = cursor.lastrowid
            conn.close()
            return {"status": "created", "id": artifact_id}
        except Exception as e:
            return {"error": str(e)}
