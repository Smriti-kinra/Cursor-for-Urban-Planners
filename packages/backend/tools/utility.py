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
from tools.geo import area_breakdown


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    dlon, dlat = math.radians(lon2 - lon1), math.radians(lat2 - lat1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


class UtilityServer:
    description = "Cross-cutting utility tools (search, geocoding, measurements, artifacts)"
    tool_names = {
        "web_search", "geocode", "measure_distance", "measure_area",
        "create_artifact", "list_artifacts", "get_artifact",
    }

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
                description=(
                    "Calculate geodesic area + perimeter of a polygon (m², hectares, km², acres). "
                    "Handles holes and MultiPolygons via the WGS84 ellipsoid."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "polygon": {
                            "type": "array",
                            "description": "Array of [longitude, latitude] pairs forming the polygon",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "geojson": {
                            "type": "object",
                            "description": "Alternative: full GeoJSON Feature/geometry — required for polygons with holes or MultiPolygons.",
                        },
                    },
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
            ToolDeclaration(
                name="list_artifacts",
                description=(
                    "List previously saved artifacts. Returns id, title, artifact_type, "
                    "created_at, updated_at, and a short content preview. Use this to "
                    "reference or extend prior analyses."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_type": {
                            "type": "string",
                            "description": "Optional filter by type (note, analysis, report, sketch).",
                        },
                        "limit": {
                            "type": "number",
                            "description": "Max number of artifacts to return (default 20).",
                        },
                    },
                },
            ),
            ToolDeclaration(
                name="get_artifact",
                description="Read the full content of a saved artifact by id.",
                parameters={
                    "type": "object",
                    "properties": {
                        "id": {"type": "number", "description": "Artifact id"},
                    },
                    "required": ["id"],
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
            return self._measure_area(args)
        if tool_name == "create_artifact":
            return self._create_artifact(args)
        if tool_name == "list_artifacts":
            return self._list_artifacts(args)
        if tool_name == "get_artifact":
            return self._get_artifact(args)
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

    def _measure_area(self, args: dict) -> dict:
        polygon = args.get("polygon")
        geojson_input = args.get("geojson")
        try:
            if geojson_input:
                geom_dict = (
                    geojson_input.get("geometry", geojson_input)
                    if isinstance(geojson_input, dict) else geojson_input
                )
                return area_breakdown(geom_dict)
            if polygon:
                if len(polygon) < 3:
                    return {"error": "Need at least 3 coordinate pairs"}
                return area_breakdown(polygon)
            return {"error": "Provide either 'polygon' (ring) or 'geojson'"}
        except Exception as e:
            return {"error": str(e)}

    def _create_artifact(self, args: dict) -> dict:
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
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

    def _list_artifacts(self, args: dict) -> dict:
        try:
            limit = int(args.get("limit", 20))
            limit = max(1, min(limit, 100))
            artifact_type = args.get("artifact_type")
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            if artifact_type:
                rows = conn.execute(
                    "SELECT id, title, artifact_type, content, created_at, updated_at "
                    "FROM artifacts WHERE artifact_type = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (artifact_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, title, artifact_type, content, created_at, updated_at "
                    "FROM artifacts ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            conn.close()
            return {
                "artifacts": [
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "artifact_type": r["artifact_type"],
                        "preview": (r["content"] or "")[:200],
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                    }
                    for r in rows
                ],
                "count": len(rows),
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_artifact(self, args: dict) -> dict:
        try:
            artifact_id = int(args.get("id"))
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, title, artifact_type, content, created_at, updated_at "
                "FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            conn.close()
            if not row:
                return {"error": f"Artifact {artifact_id} not found"}
            return dict(row)
        except Exception as e:
            return {"error": str(e)}
