#!/usr/bin/env python
"""
Urban Planners MCP Bridge

A proper MCP stdio server that exposes all urban planning tools to opencode.
Wraps the existing server classes (OSM, GIS, Weather, Zoning, Demographics)
and adds utility tools (web_search, geocode, measure, create_artifact).

Action tools (fly_to, add_geojson, etc.) POST to the Python WebSocket bridge
at BRIDGE_URL so they are relayed to the frontend.

Run by opencode as a subprocess: python packages/backend/mcp_bridge.py
"""

import asyncio
import json
import math
import os
import sqlite3
import sys
from pathlib import Path

# Ensure the backend package is importable regardless of working directory
_BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(_BACKEND_DIR / ".env")

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from mcp_servers.osm_server import OSMServer
from mcp_servers.gis_server import GISServer
from mcp_servers.weather_server import WeatherServer
from mcp_servers.zoning_server import ZoningServer
from mcp_servers.demographics_server import DemographicsServer

BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://localhost:8765")
DB_PATH = Path(os.environ.get("CURSOR_URBAN_DB", str(_BACKEND_DIR / "cursor_urban.db")))

# ── Server instances ──────────────────────────────────────────────────────────

_servers = {
    "osm": OSMServer(),
    "gis": GISServer(),
    "weather": WeatherServer(),
    "zoning": ZoningServer(),
    "demographics": DemographicsServer(),
}

# ── Action tools ──────────────────────────────────────────────────────────────

ACTION_TOOLS = {
    "fly_to", "fit_bounds",
    "add_marker", "add_markers", "clear_markers",
    "draw_line", "draw_polygon", "draw_circle", "add_geojson",
    "highlight_features", "set_layer_style", "toggle_layer", "remove_layer",
    "save_bookmark", "go_to_bookmark", "export_region_clip",
}

_ACTION_DECLARATIONS = [
    Tool(
        name="fly_to",
        description="Animate the map to specific coordinates",
        inputSchema={
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lng": {"type": "number", "description": "Longitude"},
                "zoom": {"type": "number", "description": "Zoom level 1-20, default 15"},
            },
            "required": ["lat", "lng"],
        },
    ),
    Tool(
        name="fit_bounds",
        description="Fit the map view to show a bounding box",
        inputSchema={
            "type": "object",
            "properties": {
                "south": {"type": "number"},
                "west": {"type": "number"},
                "north": {"type": "number"},
                "east": {"type": "number"},
            },
            "required": ["south", "west", "north", "east"],
        },
    ),
    Tool(
        name="add_marker",
        description="Add a labeled marker pin on the map at given coordinates",
        inputSchema={
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "label": {"type": "string", "description": "Label text for the marker popup"},
                "color": {"type": "string", "description": "CSS color (default #e6194b)"},
            },
            "required": ["lat", "lng", "label"],
        },
    ),
    Tool(
        name="add_markers",
        description="Add multiple markers at once",
        inputSchema={
            "type": "object",
            "properties": {
                "markers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lng": {"type": "number"},
                            "label": {"type": "string"},
                            "color": {"type": "string"},
                        },
                        "required": ["lat", "lng", "label"],
                    },
                },
            },
            "required": ["markers"],
        },
    ),
    Tool(
        name="clear_markers",
        description="Remove all AI-placed markers from the map",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="draw_line",
        description="Draw a line/polyline on the map between a series of points",
        inputSchema={
            "type": "object",
            "properties": {
                "coordinates": {
                    "type": "array",
                    "description": "Array of [longitude, latitude] pairs",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "color": {"type": "string", "description": "Line color (default #ef4444)"},
                "width": {"type": "number", "description": "Line width in pixels (default 3)"},
                "label": {"type": "string"},
            },
            "required": ["coordinates"],
        },
    ),
    Tool(
        name="draw_polygon",
        description="Draw a filled polygon on the map",
        inputSchema={
            "type": "object",
            "properties": {
                "coordinates": {
                    "type": "array",
                    "description": "Array of [longitude, latitude] pairs forming the polygon boundary",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "color": {"type": "string", "description": "Fill/stroke color (default #3b82f6)"},
                "opacity": {"type": "number", "description": "Fill opacity 0-1 (default 0.3)"},
                "label": {"type": "string"},
            },
            "required": ["coordinates"],
        },
    ),
    Tool(
        name="draw_circle",
        description="Draw a circle (buffer zone) on the map centered at a point",
        inputSchema={
            "type": "object",
            "properties": {
                "center_lat": {"type": "number"},
                "center_lng": {"type": "number"},
                "radius_km": {"type": "number"},
                "color": {"type": "string", "description": "Color (default #8b5cf6)"},
                "label": {"type": "string"},
            },
            "required": ["center_lat", "center_lng", "radius_km"],
        },
    ),
    Tool(
        name="add_geojson",
        description="Add a GeoJSON FeatureCollection as a new map layer",
        inputSchema={
            "type": "object",
            "properties": {
                "geojson": {"type": "object", "description": "A GeoJSON FeatureCollection object"},
                "name": {"type": "string", "description": "Display name for the layer"},
                "color": {"type": "string"},
            },
            "required": ["geojson", "name"],
        },
    ),
    Tool(
        name="highlight_features",
        description="Highlight features in a loaded layer by filtering on a property value",
        inputSchema={
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"},
                "property_name": {"type": "string"},
                "property_value": {"type": "string"},
            },
            "required": ["layer_name", "property_name", "property_value"],
        },
    ),
    Tool(
        name="set_layer_style",
        description="Change the visual style of a loaded map layer",
        inputSchema={
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"},
                "fill_color": {"type": "string"},
                "line_color": {"type": "string"},
                "opacity": {"type": "number"},
            },
            "required": ["layer_name"],
        },
    ),
    Tool(
        name="toggle_layer",
        description="Show or hide a map layer",
        inputSchema={
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"},
                "visible": {"type": "boolean"},
            },
            "required": ["layer_name", "visible"],
        },
    ),
    Tool(
        name="remove_layer",
        description="Remove a layer from the map entirely",
        inputSchema={
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"},
            },
            "required": ["layer_name"],
        },
    ),
    Tool(
        name="save_bookmark",
        description=(
            "Save the current map region as a named bookmark for quick return. "
            "If south/west/north/east are omitted, the app uses the current visible map bounds from context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "south": {"type": "number"},
                "west": {"type": "number"},
                "north": {"type": "number"},
                "east": {"type": "number"},
                "zoom": {"type": "number"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="go_to_bookmark",
        description="Fly the map to a previously saved bookmark by name",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="export_region_clip",
        description=(
            "Clip all loaded layers to a bounding box and save a merged GeoJSON into the workspace. "
            "Requires an open workspace folder. If bbox omitted, uses current map bounds from context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "output_base_name": {"type": "string"},
                "south": {"type": "number"},
                "west": {"type": "number"},
                "north": {"type": "number"},
                "east": {"type": "number"},
            },
            "required": ["output_base_name"],
        },
    ),
]

# ── Utility tool declarations ─────────────────────────────────────────────────

_UTIL_DECLARATIONS = [
    Tool(
        name="web_search",
        description="Search the web for urban planning info, regulations, demographics, real estate",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    Tool(
        name="geocode",
        description="Convert an address or place name to geographic coordinates",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Address or place name"}},
            "required": ["query"],
        },
    ),
    Tool(
        name="measure_distance",
        description="Calculate the distance along a series of points (in km and miles)",
        inputSchema={
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
    Tool(
        name="measure_area",
        description="Calculate the area of a polygon (in m², hectares, km²)",
        inputSchema={
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
    Tool(
        name="create_artifact",
        description="Save a note, analysis, or report as an artifact in the project",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "artifact_type": {
                    "type": "string",
                    "description": "Type: note, analysis, report, or sketch",
                },
            },
            "required": ["title", "content", "artifact_type"],
        },
    ),
]

# ── Utility implementations ───────────────────────────────────────────────────

async def _web_search(query: str) -> dict:
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


async def _geocode(query: str) -> dict:
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


def _haversine(lon1, lat1, lon2, lat2):
    R = 6371.0
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _measure_distance(points: list) -> dict:
    if len(points) < 2:
        return {"error": "Need at least 2 points"}
    total_km = sum(_haversine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1]) for i in range(len(points) - 1))
    return {
        "distance_km": round(total_km, 4),
        "distance_miles": round(total_km * 0.621371, 4),
        "distance_meters": round(total_km * 1000, 1),
    }


def _shoelace_area(coords):
    n = len(coords)
    if n < 3:
        return 0
    R = 6371000.0
    area = 0
    for i in range(n):
        j = (i + 1) % n
        xi = math.radians(coords[i][0]) * R * math.cos(math.radians(coords[i][1]))
        yi = math.radians(coords[i][1]) * R
        xj = math.radians(coords[j][0]) * R * math.cos(math.radians(coords[j][1]))
        yj = math.radians(coords[j][1]) * R
        area += xi * yj - xj * yi
    return abs(area) / 2


def _measure_area(polygon: list) -> dict:
    if len(polygon) < 3:
        return {"error": "Need at least 3 points"}
    area_m2 = _shoelace_area(polygon)
    return {
        "area_m2": round(area_m2, 1),
        "area_hectares": round(area_m2 / 10000, 4),
        "area_km2": round(area_m2 / 1e6, 6),
        "area_acres": round(area_m2 / 4046.86, 4),
    }


def _create_artifact(args: dict) -> dict:
    try:
        conn = sqlite3.connect(str(DB_PATH))
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


# ── Bridge relay ──────────────────────────────────────────────────────────────

async def _post_action(action: str, payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{BRIDGE_URL}/internal/action",
                json={"action": action, "payload": payload},
            )
    except Exception:
        pass


# ── MCP server ────────────────────────────────────────────────────────────────

server = Server("urban-planners")


@server.list_tools()
async def list_tools() -> list[Tool]:
    tools: list[Tool] = []
    tools.extend(_ACTION_DECLARATIONS)
    tools.extend(_UTIL_DECLARATIONS)
    for srv in _servers.values():
        for decl in srv.get_declarations():
            tools.append(Tool(
                name=decl.name,
                description=decl.description,
                inputSchema=decl.parameters,
            ))
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    result = await _execute(name, arguments)
    return [TextContent(type="text", text=json.dumps(result))]


async def _execute(name: str, args: dict) -> dict:
    # Action tools — relay to Python bridge
    if name in ACTION_TOOLS:
        await _post_action(name, args)
        if name == "create_artifact":
            pass  # handled below
        return {"status": "success", "message": f"Map action '{name}' executed."}

    # Utility tools
    if name == "web_search":
        return await _web_search(args.get("query", ""))
    if name == "geocode":
        return await _geocode(args.get("query", ""))
    if name == "measure_distance":
        return _measure_distance(args.get("points", []))
    if name == "measure_area":
        return _measure_area(args.get("polygon", []))
    if name == "create_artifact":
        result = _create_artifact(args)
        await _post_action("refresh_artifacts", {})
        return result

    # MCP server tools
    for srv in _servers.values():
        if name in srv.tool_names:
            result = await srv.execute(name, args)

            # Auto-display: osm_search → add_geojson
            if name == "osm_search" and "geojson" in result and result.get("count", 0) > 0:
                label = f"{args.get('feature_value', 'features')} ({args.get('feature_type', '')})"
                await _post_action("add_geojson", {"geojson": result["geojson"], "name": label})
                features_summary = []
                for f in result["geojson"].get("features", [])[:50]:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    entry = {"name": props.get("name", "")}
                    if geom.get("type") == "Point":
                        entry["lat"] = geom["coordinates"][1]
                        entry["lng"] = geom["coordinates"][0]
                    elif geom.get("coordinates"):
                        coords = geom["coordinates"]
                        if geom["type"] == "Polygon":
                            coords = coords[0]
                        if coords:
                            entry["lat"] = round(sum(c[1] for c in coords) / len(coords), 6)
                            entry["lng"] = round(sum(c[0] for c in coords) / len(coords), 6)
                    features_summary.append(entry)
                del result["geojson"]
                result["displayed_on_map"] = True
                result["features"] = features_summary

            # Auto-display: osm_boundary → add_geojson
            elif name == "osm_boundary" and "geojson" in result:
                label = f"{args.get('name', 'Boundary')} boundary"
                await _post_action("add_geojson", {"geojson": result["geojson"], "name": label})
                del result["geojson"]
                result["displayed_on_map"] = True

            # Auto-display: osm_route_overview → draw_line
            elif name == "osm_route_overview" and "geometry" in result:
                await _post_action("draw_line", {
                    "coordinates": result["geometry"]["coordinates"],
                    "color": "#2563eb",
                    "width": 4,
                    "label": f"Route ({result.get('distance_km', '?')} km)",
                })

            # Auto-display: gis_buffer → add_geojson
            elif name == "gis_buffer" and "geojson" in result:
                await _post_action("add_geojson", {
                    "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                    "name": f"Buffer ({args.get('radius_meters', '?')}m)",
                })

            # Auto-display: gis_convex_hull → add_geojson
            elif name == "gis_convex_hull" and "geojson" in result:
                await _post_action("add_geojson", {
                    "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                    "name": "Convex Hull",
                })

            # Auto-display: gis_union → add_geojson
            elif name == "gis_union" and "geojson" in result:
                await _post_action("add_geojson", {
                    "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                    "name": "Union",
                })

            return result

    return {"error": f"Unknown tool: {name}"}


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
