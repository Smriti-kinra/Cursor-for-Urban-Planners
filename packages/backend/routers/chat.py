from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
import json
import os
import math
import httpx

from mcp_servers import MCPManager

router = APIRouter()
mcp = MCPManager()

SYSTEM_PROMPT = (
    "You are an expert urban planning assistant embedded in a desktop GIS application. "
    "You help with zoning analysis, land use planning, transportation networks, "
    "environmental impact, building codes, community development, and spatial analysis.\n\n"
    "You have FULL control over the map. You can:\n"
    "- Navigate: fly_to any location, fit_bounds to zoom to an area\n"
    "- Markers: add_marker, add_markers, clear_markers to annotate locations\n"
    "- Draw: draw_line, draw_polygon, draw_circle to sketch geometry on the map\n"
    "- Layers: add_geojson to load data, toggle_layer/remove_layer/set_layer_style to manage\n"
    "- Highlight: highlight_features to filter and emphasize features\n"
    "- Measure: measure_distance, measure_area for spatial calculations\n"
    "- Search: web_search for information, geocode for coordinates\n"
    "- OSM: osm_search to find real-world features (buildings, roads, amenities), "
    "osm_reverse_geocode for address lookup, osm_route_overview for routing\n"
    "- Weather: get_weather and get_air_quality for environmental data\n"
    "- GIS Analysis: gis_buffer, gis_centroid, gis_area, gis_convex_hull, "
    "gis_point_in_polygon, gis_bounding_box, gis_union\n"
    "- Artifacts: create_artifact to save findings\n\n"
    "Use these tools proactively. When the user asks about a place, fly there AND add markers. "
    "When they ask about nearby amenities, use osm_search (results auto-display on map). "
    "When they ask about distances, measure them. Be visual and action-oriented."
)

# Core tools that are NOT provided by MCP servers
CORE_TOOL_DECLARATIONS = [
    # ── Search ──
    types.FunctionDeclaration(
        name="web_search",
        description="Search the web for urban planning info, regulations, demographics, real estate",
        parameters={
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "The search query"},
            },
            "required": ["query"],
        },
    ),
    types.FunctionDeclaration(
        name="geocode",
        description="Convert an address or place name to geographic coordinates",
        parameters={
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Address or place name"},
            },
            "required": ["query"],
        },
    ),

    # ── Navigation ──
    types.FunctionDeclaration(
        name="fly_to",
        description="Animate the map to specific coordinates",
        parameters={
            "type": "OBJECT",
            "properties": {
                "lat": {"type": "NUMBER", "description": "Latitude"},
                "lng": {"type": "NUMBER", "description": "Longitude"},
                "zoom": {"type": "NUMBER", "description": "Zoom level 1-20, default 15"},
            },
            "required": ["lat", "lng"],
        },
    ),
    types.FunctionDeclaration(
        name="fit_bounds",
        description="Fit the map view to show a bounding box",
        parameters={
            "type": "OBJECT",
            "properties": {
                "south": {"type": "NUMBER", "description": "South latitude"},
                "west": {"type": "NUMBER", "description": "West longitude"},
                "north": {"type": "NUMBER", "description": "North latitude"},
                "east": {"type": "NUMBER", "description": "East longitude"},
            },
            "required": ["south", "west", "north", "east"],
        },
    ),

    # ── Markers ──
    types.FunctionDeclaration(
        name="add_marker",
        description="Add a labeled marker pin on the map at given coordinates",
        parameters={
            "type": "OBJECT",
            "properties": {
                "lat": {"type": "NUMBER", "description": "Latitude"},
                "lng": {"type": "NUMBER", "description": "Longitude"},
                "label": {"type": "STRING", "description": "Label text for the marker popup"},
                "color": {"type": "STRING", "description": "CSS color (default #e6194b)"},
            },
            "required": ["lat", "lng", "label"],
        },
    ),
    types.FunctionDeclaration(
        name="add_markers",
        description="Add multiple markers at once. Use for showing a set of locations.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "markers": {
                    "type": "ARRAY",
                    "description": "Array of marker objects",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "lat": {"type": "NUMBER"},
                            "lng": {"type": "NUMBER"},
                            "label": {"type": "STRING"},
                            "color": {"type": "STRING"},
                        },
                        "required": ["lat", "lng", "label"],
                    },
                },
            },
            "required": ["markers"],
        },
    ),
    types.FunctionDeclaration(
        name="clear_markers",
        description="Remove all AI-placed markers from the map",
        parameters={"type": "OBJECT", "properties": {}},
    ),

    # ── Drawing ──
    types.FunctionDeclaration(
        name="draw_line",
        description="Draw a line/polyline on the map between a series of points",
        parameters={
            "type": "OBJECT",
            "properties": {
                "coordinates": {
                    "type": "ARRAY",
                    "description": "Array of [longitude, latitude] pairs",
                    "items": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                },
                "color": {"type": "STRING", "description": "Line color (default #ef4444)"},
                "width": {"type": "NUMBER", "description": "Line width in pixels (default 3)"},
                "label": {"type": "STRING", "description": "Optional label for this line"},
            },
            "required": ["coordinates"],
        },
    ),
    types.FunctionDeclaration(
        name="draw_polygon",
        description="Draw a filled polygon on the map. Coordinates should form a closed ring.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "coordinates": {
                    "type": "ARRAY",
                    "description": "Array of [longitude, latitude] pairs forming the polygon boundary",
                    "items": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                },
                "color": {"type": "STRING", "description": "Fill/stroke color (default #3b82f6)"},
                "opacity": {"type": "NUMBER", "description": "Fill opacity 0-1 (default 0.3)"},
                "label": {"type": "STRING", "description": "Optional label for this polygon"},
            },
            "required": ["coordinates"],
        },
    ),
    types.FunctionDeclaration(
        name="draw_circle",
        description="Draw a circle (buffer zone) on the map centered at a point",
        parameters={
            "type": "OBJECT",
            "properties": {
                "center_lat": {"type": "NUMBER", "description": "Center latitude"},
                "center_lng": {"type": "NUMBER", "description": "Center longitude"},
                "radius_km": {"type": "NUMBER", "description": "Radius in kilometers"},
                "color": {"type": "STRING", "description": "Color (default #8b5cf6)"},
                "label": {"type": "STRING", "description": "Optional label"},
            },
            "required": ["center_lat", "center_lng", "radius_km"],
        },
    ),
    types.FunctionDeclaration(
        name="add_geojson",
        description="Add a GeoJSON FeatureCollection as a new map layer",
        parameters={
            "type": "OBJECT",
            "properties": {
                "geojson": {"type": "OBJECT", "description": "A GeoJSON FeatureCollection object"},
                "name": {"type": "STRING", "description": "Display name for the layer"},
                "color": {"type": "STRING", "description": "Layer color (default auto)"},
            },
            "required": ["geojson", "name"],
        },
    ),

    # ── Layer management ──
    types.FunctionDeclaration(
        name="highlight_features",
        description="Highlight features in a loaded layer by filtering on a property value",
        parameters={
            "type": "OBJECT",
            "properties": {
                "layer_name": {"type": "STRING", "description": "Name of the layer"},
                "property_name": {"type": "STRING", "description": "Property to filter by"},
                "property_value": {"type": "STRING", "description": "Value to match"},
            },
            "required": ["layer_name", "property_name", "property_value"],
        },
    ),
    types.FunctionDeclaration(
        name="set_layer_style",
        description="Change the visual style of a loaded map layer",
        parameters={
            "type": "OBJECT",
            "properties": {
                "layer_name": {"type": "STRING", "description": "Name of the layer"},
                "fill_color": {"type": "STRING", "description": "New fill color"},
                "line_color": {"type": "STRING", "description": "New line/outline color"},
                "opacity": {"type": "NUMBER", "description": "Fill opacity 0-1"},
            },
            "required": ["layer_name"],
        },
    ),
    types.FunctionDeclaration(
        name="toggle_layer",
        description="Show or hide a map layer",
        parameters={
            "type": "OBJECT",
            "properties": {
                "layer_name": {"type": "STRING", "description": "Name of the layer"},
                "visible": {"type": "BOOLEAN", "description": "true to show, false to hide"},
            },
            "required": ["layer_name", "visible"],
        },
    ),
    types.FunctionDeclaration(
        name="remove_layer",
        description="Remove a layer from the map entirely",
        parameters={
            "type": "OBJECT",
            "properties": {
                "layer_name": {"type": "STRING", "description": "Name of the layer to remove"},
            },
            "required": ["layer_name"],
        },
    ),

    # ── Measurement ──
    types.FunctionDeclaration(
        name="measure_distance",
        description="Calculate the distance along a series of points (in km and miles)",
        parameters={
            "type": "OBJECT",
            "properties": {
                "points": {
                    "type": "ARRAY",
                    "description": "Array of [longitude, latitude] pairs",
                    "items": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                },
            },
            "required": ["points"],
        },
    ),
    types.FunctionDeclaration(
        name="measure_area",
        description="Calculate the area of a polygon (in m², hectares, km²)",
        parameters={
            "type": "OBJECT",
            "properties": {
                "polygon": {
                    "type": "ARRAY",
                    "description": "Array of [longitude, latitude] pairs forming the polygon",
                    "items": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                },
            },
            "required": ["polygon"],
        },
    ),

    # ── Artifacts ──
    types.FunctionDeclaration(
        name="create_artifact",
        description="Save a note, analysis, or report as an artifact in the project",
        parameters={
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Title of the artifact"},
                "content": {"type": "STRING", "description": "Content text"},
                "artifact_type": {
                    "type": "STRING",
                    "description": "Type: note, analysis, report, or sketch",
                },
            },
            "required": ["title", "content", "artifact_type"],
        },
    ),
]

ACTION_TOOLS = {
    "fly_to", "fit_bounds",
    "add_marker", "add_markers", "clear_markers",
    "draw_line", "draw_polygon", "draw_circle", "add_geojson",
    "highlight_features", "set_layer_style", "toggle_layer", "remove_layer",
}


def get_all_tool_declarations() -> list[types.Tool]:
    """Merge core tool declarations with MCP server declarations."""
    mcp_tools = mcp.get_tool_declarations()
    mcp_decls = []
    for tool in mcp_tools:
        if tool.function_declarations:
            mcp_decls.extend(tool.function_declarations)
    return [types.Tool(function_declarations=CORE_TOOL_DECLARATIONS + mcp_decls)]


def get_client():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


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


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    client = get_client()
    history: list = []
    all_tools = get_all_tool_declarations()

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            user_content = message.get("content", "")
            map_context = message.get("map_context")

            if not client:
                await websocket.send_text(json.dumps({
                    "type": "stream",
                    "content": "GEMINI_API_KEY is not set. Add it to packages/backend/.env",
                }))
                await websocket.send_text(json.dumps({"type": "end"}))
                continue

            system = SYSTEM_PROMPT
            if map_context:
                system += f"\n\nCurrent map state:\n{json.dumps(map_context, indent=2)}"

            history.append({"role": "user", "parts": [{"text": user_content}]})

            config = types.GenerateContentConfig(
                system_instruction=system,
                tools=all_tools,
            )

            try:
                for _round in range(8):
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=history,
                        config=config,
                    )

                    if not response.candidates:
                        await websocket.send_text(json.dumps({
                            "type": "stream", "content": "No response generated.",
                        }))
                        break

                    candidate = response.candidates[0]
                    parts = candidate.content.parts
                    func_calls = [p for p in parts if getattr(p, "function_call", None)]

                    if not func_calls:
                        text = "".join(p.text for p in parts if getattr(p, "text", None))
                        if text:
                            await websocket.send_text(json.dumps({"type": "stream", "content": text}))
                            history.append({"role": "model", "parts": [{"text": text}]})
                        break

                    history.append(candidate.content)
                    func_response_parts = []

                    for part in func_calls:
                        fc = part.function_call
                        func_name = fc.name
                        func_args = dict(fc.args) if fc.args else {}

                        await websocket.send_text(json.dumps({
                            "type": "tool_use", "tool": func_name, "args": func_args,
                        }))

                        result = None

                        # 1) Frontend pass-through actions
                        if func_name in ACTION_TOOLS:
                            await websocket.send_text(json.dumps({
                                "type": "action", "action": func_name, "payload": func_args,
                            }))
                            result = {"status": "success", "message": f"Map action '{func_name}' executed."}

                        # 2) Core tools handled in this file
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

                        # 3) MCP server tools
                        elif mcp.owns_tool(func_name):
                            result = await mcp.execute(func_name, func_args)

                            # Auto-display OSM search results on map
                            if func_name == "osm_search" and "geojson" in result and result.get("count", 0) > 0:
                                label = f"{func_args.get('feature_value', 'features')} ({func_args.get('feature_type', '')})"
                                await websocket.send_text(json.dumps({
                                    "type": "action",
                                    "action": "add_geojson",
                                    "payload": {"geojson": result["geojson"], "name": label},
                                }))
                                del result["geojson"]
                                result["displayed_on_map"] = True

                            # Auto-display route geometry
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

                            # Auto-display GIS buffer results
                            if func_name == "gis_buffer" and "geojson" in result:
                                await websocket.send_text(json.dumps({
                                    "type": "action",
                                    "action": "add_geojson",
                                    "payload": {
                                        "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                                        "name": f"Buffer ({func_args.get('radius_meters', '?')}m)",
                                    },
                                }))

                            # Auto-display convex hull
                            if func_name == "gis_convex_hull" and "geojson" in result:
                                await websocket.send_text(json.dumps({
                                    "type": "action",
                                    "action": "add_geojson",
                                    "payload": {
                                        "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                                        "name": "Convex Hull",
                                    },
                                }))

                            # Auto-display union result
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

                        func_response_parts.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=func_name, response=result,
                                )
                            )
                        )

                    history.append(types.Content(role="user", parts=func_response_parts))

            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "stream", "content": f"\n\n[Error from Gemini: {e}]",
                }))

            await websocket.send_text(json.dumps({"type": "end"}))
    except WebSocketDisconnect:
        pass
