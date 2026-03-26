from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import os
import math
import httpx

from llm import get_provider
from llm.base import Message, ToolDeclaration
from tools import CORE_TOOLS
from mcp_servers import MCPManager

router = APIRouter()
mcp = MCPManager()

SYSTEM_PROMPT = (
    "You are an expert urban planning assistant embedded in a desktop GIS application. "
    "You help with zoning analysis, land use planning, transportation networks, "
    "environmental impact, building codes, community development, and spatial analysis.\n\n"
    "AVAILABLE TOOLS:\n"
    "- Navigate: fly_to, fit_bounds\n"
    "- Markers: add_marker, add_markers, clear_markers\n"
    "- Draw: draw_line, draw_polygon, draw_circle\n"
    "- Layers: add_geojson, toggle_layer, remove_layer, set_layer_style\n"
    "- Highlight: highlight_features\n"
    "- Measure: measure_distance, measure_area\n"
    "- Search: web_search, geocode\n"
    "- OSM: osm_search (amenities, buildings, roads), "
    "osm_boundary (city/district/state boundary polygons), "
    "osm_reverse_geocode, osm_route_overview\n"
    "- Weather: get_weather, get_air_quality\n"
    "- GIS: gis_buffer, gis_centroid, gis_area, gis_convex_hull, "
    "gis_point_in_polygon, gis_bounding_box, gis_union\n"
    "- Bookmarks: save_bookmark, go_to_bookmark, export_region_clip (clip layers to bbox / workspace)\n"
    "- Zoning: analyze_zones, detect_zone_overlaps (GeoJSON with zone_code on polygons)\n"
    "- Demographics: get_demographics (OSM population tags + reverse geocode near a point)\n"
    "- Artifacts: create_artifact\n\n"
    "MAP CONTEXT:\n"
    "The current map state is appended to every message. It includes:\n"
    "- bounds: current viewport (west,south,east,north) when available — use for save_bookmark / export_region_clip.\n"
    "- bookmarks: saved regions (name + bbox + zoom); use go_to_bookmark to navigate.\n"
    "- Layer list with geometry_data (actual coordinates for small layers, bbox for large ones).\n"
    "- You can use geometry_data from existing layers to compute centroids, buffers, etc. "
    "Pass coordinates directly to gis_centroid, gis_buffer, or other GIS tools.\n\n"
    "IMPORTANT RULES:\n"
    "1. Do NOT add markers unless the user explicitly asks for markers or pins.\n"
    "2. Do NOT repeat a tool call you already made. Call each tool ONCE per distinct item.\n"
    "3. osm_search and osm_boundary results are AUTO-DISPLAYED on the map. "
    "Do NOT call add_geojson for data that was already returned by these tools.\n"
    "4. When using osm_boundary, ALWAYS pass country_code (e.g. 'IN' for India) to avoid wrong matches.\n"
    "5. Only call the tools the user's request requires. Do not add extra actions.\n"
    "6. When the user asks to navigate somewhere, use fly_to. Do not add markers unless asked.\n"
    "7. When finished, stop calling tools and respond with a brief summary of what you did."
)

ACTION_TOOLS = {
    "fly_to", "fit_bounds",
    "add_marker", "add_markers", "clear_markers",
    "draw_line", "draw_polygon", "draw_circle", "add_geojson",
    "highlight_features", "set_layer_style", "toggle_layer", "remove_layer",
    "save_bookmark", "go_to_bookmark", "export_region_clip",
}


def get_all_tool_declarations() -> list[ToolDeclaration]:
    """Merge core tool declarations with MCP server declarations."""
    return CORE_TOOLS + mcp.get_tool_declarations()


# ── Core tool execution (non-MCP) ──

async def execute_web_search(query: str) -> dict:
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


async def execute_geocode(query: str) -> dict:
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


def execute_measure_distance(points: list) -> dict:
    if len(points) < 2:
        return {"error": "Need at least 2 points"}
    total_km = 0
    for i in range(len(points) - 1):
        total_km += _haversine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
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


def execute_measure_area(polygon: list) -> dict:
    if len(polygon) < 3:
        return {"error": "Need at least 3 points"}
    area_m2 = _shoelace_area(polygon)
    return {
        "area_m2": round(area_m2, 1),
        "area_hectares": round(area_m2 / 10000, 4),
        "area_km2": round(area_m2 / 1e6, 6),
        "area_acres": round(area_m2 / 4046.86, 4),
    }


def create_artifact_in_db(args: dict) -> dict:
    try:
        from database import get_connection
        conn = get_connection()
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


async def run_tool(func_name: str, func_args: dict, websocket: WebSocket) -> dict:
    """Execute a tool call and handle side-effects (map actions, auto-display)."""
    result = None

    if func_name in ACTION_TOOLS:
        await websocket.send_text(json.dumps({
            "type": "action", "action": func_name, "payload": func_args,
        }))
        result = {"status": "success", "message": f"Map action '{func_name}' executed."}

    elif func_name == "web_search":
        result = await execute_web_search(func_args.get("query", ""))
    elif func_name == "geocode":
        result = await execute_geocode(func_args.get("query", ""))
    elif func_name == "measure_distance":
        result = execute_measure_distance(func_args.get("points", []))
    elif func_name == "measure_area":
        result = execute_measure_area(func_args.get("polygon", []))
    elif func_name == "create_artifact":
        result = create_artifact_in_db(func_args)
        await websocket.send_text(json.dumps({
            "type": "action", "action": "refresh_artifacts", "payload": {},
        }))

    elif mcp.owns_tool(func_name):
        result = await mcp.execute(func_name, func_args)

        if func_name == "osm_search" and "geojson" in result and result.get("count", 0) > 0:
            label = f"{func_args.get('feature_value', 'features')} ({func_args.get('feature_type', '')})"
            await websocket.send_text(json.dumps({
                "type": "action",
                "action": "add_geojson",
                "payload": {"geojson": result["geojson"], "name": label},
            }))
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
                        avg_lng = sum(c[0] for c in coords) / len(coords)
                        avg_lat = sum(c[1] for c in coords) / len(coords)
                        entry["lat"] = round(avg_lat, 6)
                        entry["lng"] = round(avg_lng, 6)
                features_summary.append(entry)
            del result["geojson"]
            result["displayed_on_map"] = True
            result["features"] = features_summary

        if func_name == "osm_boundary" and "geojson" in result:
            label = f"{func_args.get('name', 'Boundary')} boundary"
            await websocket.send_text(json.dumps({
                "type": "action",
                "action": "add_geojson",
                "payload": {"geojson": result["geojson"], "name": label},
            }))
            del result["geojson"]
            result["displayed_on_map"] = True

        if func_name == "osm_route_overview" and "geometry" in result:
            await websocket.send_text(json.dumps({
                "type": "action",
                "action": "draw_line",
                "payload": {
                    "coordinates": result["geometry"]["coordinates"],
                    "color": "#2563eb",
                    "width": 4,
                    "label": f"Route ({result.get('distance_km', '?')} km)",
                },
            }))

        if func_name == "gis_buffer" and "geojson" in result:
            await websocket.send_text(json.dumps({
                "type": "action",
                "action": "add_geojson",
                "payload": {
                    "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                    "name": f"Buffer ({func_args.get('radius_meters', '?')}m)",
                },
            }))

        if func_name == "gis_convex_hull" and "geojson" in result:
            await websocket.send_text(json.dumps({
                "type": "action",
                "action": "add_geojson",
                "payload": {
                    "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                    "name": "Convex Hull",
                },
            }))

        if func_name == "gis_union" and "geojson" in result:
            await websocket.send_text(json.dumps({
                "type": "action",
                "action": "add_geojson",
                "payload": {
                    "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                    "name": "Union",
                },
            }))

    else:
        result = {"error": f"Unknown function: {func_name}"}

    return result


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    provider = get_provider()
    history: list[Message] = []
    all_tools = get_all_tool_declarations()

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            user_content = message.get("content", "")
            map_context = message.get("map_context")

            if not provider:
                await websocket.send_text(json.dumps({
                    "type": "stream",
                    "content": "LLM provider not configured. Make sure Ollama is running and check packages/backend/.env",
                }))
                await websocket.send_text(json.dumps({"type": "end"}))
                continue

            system = SYSTEM_PROMPT
            if map_context:
                system += f"\n\nCurrent map state:\n{json.dumps(map_context, indent=2)}"

            history.append(Message(role="user", content=user_content))

            try:
                for _round in range(5):
                    response = await provider.generate(
                        messages=history,
                        tools=all_tools,
                        system=system,
                    )

                    if not response.tool_calls:
                        if response.content:
                            await websocket.send_text(json.dumps({
                                "type": "stream", "content": response.content,
                            }))
                            history.append(Message(role="assistant", content=response.content))
                        break

                    history.append(Message(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    ))

                    for tc in response.tool_calls:
                        await websocket.send_text(json.dumps({
                            "type": "tool_use", "tool": tc.name, "args": tc.args,
                        }))

                        result = await run_tool(tc.name, tc.args, websocket)

                        history.append(Message(
                            role="tool",
                            content=json.dumps(result),
                            tool_call_id=tc.id,
                            name=tc.name,
                        ))

            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "stream", "content": f"\n\n[Error: {e}]",
                }))

            await websocket.send_text(json.dumps({"type": "end"}))
    except WebSocketDisconnect:
        pass
