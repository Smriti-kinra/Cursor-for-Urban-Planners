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

from llm.base import ToolDeclaration
from tools import cache, http as http_client
from tools.geo import area_breakdown
from tools.google import GoogleUnavailable, geocode_query as google_geocode_query, has_key as has_google_key


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    dlon, dlat = math.radians(lon2 - lon1), math.radians(lat2 - lat1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# Photon osm_key values from most-to-least preferred for place lookups.
# Prefer city/town/suburb nodes over administrative boundary centroids — this
# ensures "SAS Nagar" resolves to the city of Mohali, not the Tahsil boundary.
_PHOTON_KEY_RANK: dict[str, int] = {
    "place": 0,
    "tourism": 1,
    "amenity": 2,
    "natural": 3,
    "boundary": 10,  # administrative boundaries last — centroid often wrong
}


def _photon_to_results(payload: dict) -> list[dict]:
    raw: list[tuple[int, dict]] = []
    for feat in (payload or {}).get("features", []) or []:
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lng, lat = coords[0], coords[1]
        props = feat.get("properties") or {}
        parts = [
            props.get("name"),
            props.get("housenumber"),
            props.get("street"),
            props.get("postcode"),
            props.get("city") or props.get("locality"),
            props.get("state"),
            props.get("country"),
        ]
        display_name = ", ".join(p for p in parts if p)
        key_rank = _PHOTON_KEY_RANK.get(props.get("osm_key", ""), 5)
        raw.append((key_rank, {
            "display_name": display_name or props.get("name", ""),
            "lat": str(lat),
            "lon": str(lng),
        }))
    # Stable sort: preferred osm_key first, original Photon order preserved
    # within the same rank tier.
    raw.sort(key=lambda x: x[0])
    return [r for _, r in raw]


def _nominatim_to_results(payload: list) -> list[dict]:
    if not isinstance(payload, list):
        return []
    return [
        {
            "display_name": r.get("display_name", ""),
            "lat": r.get("lat"),
            "lon": r.get("lon"),
        }
        for r in payload
    ]


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
                description=(
                    "Save a note, analysis, report, or geospatial dataset as a project artifact. "
                    "Supported formats: 'markdown' (default), 'table', 'geojson'. "
                    "Do NOT use format='image' — images are created from the map export UI only."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {
                            "type": "string",
                            "description": (
                                "For markdown: the markdown text. "
                                "For table: JSON string '{\"columns\":[...],\"rows\":[[...]]}'. "
                                "For geojson: a GeoJSON Feature or FeatureCollection JSON string."
                            ),
                        },
                        "artifact_type": {
                            "type": "string",
                            "description": "Semantic label: note, analysis, report, or sketch",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["markdown", "table", "geojson"],
                            "description": "Payload format. Defaults to 'markdown'.",
                        },
                    },
                    "required": ["title", "content", "artifact_type"],
                },
            ),
            ToolDeclaration(
                name="list_artifacts",
                description=(
                    "List previously saved artifacts. Returns id, title, artifact_type, format, "
                    "meta, created_at, updated_at, and a short content preview. "
                    "Use this to reference or extend prior analyses."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_type": {
                            "type": "string",
                            "description": "Optional filter by type (note, analysis, report, sketch).",
                        },
                        "format": {
                            "type": "string",
                            "description": "Optional filter by format (markdown, table, image, geojson).",
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
                description=(
                    "Read the full content of a saved artifact by id. "
                    "For geojson artifacts, the returned 'content' field contains the GeoJSON string — "
                    "pass it to add_geojson to re-add it to the map."
                ),
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
        query = (query or "").strip()
        if not query:
            return {"error": "Empty query"}
        limit = 5
        cache_key = {"q": query.lower(), "limit": limit}

        async def _fetch() -> list[dict]:
            # Google Geocoding (highest accuracy, especially for India). Only
            # attempted when GOOGLE_MAPS_API_KEY is set; otherwise skip silently.
            if has_google_key():
                try:
                    google_results = await google_geocode_query(query, limit=limit)
                    if google_results:
                        # Slim down to the shape stored historically (str lat/lon)
                        # so cached entries from the Google tier are interchangeable
                        # with cached entries from the Photon/Nominatim tiers.
                        return [
                            {
                                "display_name": r["display_name"],
                                "lat": str(r["lat"]),
                                "lon": str(r["lon"]),
                            }
                            for r in google_results
                        ]
                except GoogleUnavailable:
                    pass

            try:
                photon = await http_client.fetch_json(
                    "https://photon.komoot.io/api/",
                    namespace="photon",
                    params={"q": query, "limit": limit},
                )
                results = _photon_to_results(photon)
                if results:
                    return results
            except http_client.HTTPError:
                pass

            nominatim = await http_client.fetch_json(
                "https://nominatim.openstreetmap.org/search",
                namespace="nominatim",
                params={"q": query, "format": "json", "limit": limit},
            )
            return _nominatim_to_results(nominatim)

        try:
            results = await cache.get_or_fetch(
                namespace="geocode",
                key=cache_key,
                ttl_seconds=86_400 * 7,
                fetch_fn=_fetch,
            )
        except http_client.HTTPError as e:
            return {"error": str(e), "code": e.code}
        except Exception as e:
            return {"error": str(e)}
        return {"results": results}

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
        if args.get("format") == "image":
            return {"error": "format='image' is not supported for AI artifact creation. Images must be created from the map export UI."}
        try:
            from tools.artifact_store import save_artifact
            fmt = args.get("format", "markdown")
            result = save_artifact(
                title=args.get("title", "Untitled"),
                artifact_type=args.get("artifact_type", "note"),
                format=fmt,
                content=args.get("content", ""),
            )
            return {"status": "created", "id": result["id"]}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def _list_artifacts(self, args: dict) -> dict:
        try:
            limit = int(args.get("limit", 20))
            limit = max(1, min(limit, 100))
            artifact_type = args.get("artifact_type")
            fmt = args.get("format")
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row

            conditions = []
            params: list = []
            if artifact_type:
                conditions.append("artifact_type = ?")
                params.append(artifact_type)
            if fmt:
                conditions.append("format = ?")
                params.append(fmt)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.append(limit)
            rows = conn.execute(
                f"SELECT id, title, artifact_type, format, meta, content, created_at, updated_at "
                f"FROM artifacts {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
            conn.close()
            return {
                "artifacts": [
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "artifact_type": r["artifact_type"],
                        "format": r["format"],
                        "meta": r["meta"],
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
                "SELECT id, title, artifact_type, format, meta, content, created_at, updated_at "
                "FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            conn.close()
            if not row:
                return {"error": f"Artifact {artifact_id} not found"}
            return dict(row)
        except Exception as e:
            return {"error": str(e)}
