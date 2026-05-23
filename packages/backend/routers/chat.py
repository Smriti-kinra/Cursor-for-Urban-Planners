"""
Chat router — direct OpenAI integration with tool-calling loop.

Each WebSocket connection keeps a running message history and runs an
agentic loop:
  1. Send messages to OpenAI with tool definitions.
  2. Stream text deltas back to the frontend.
  3. Execute tool calls inline; map actions go straight to the WebSocket.
  4. Loop until the model stops calling tools.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI

# Make sure backend package is importable
_BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from database import DB_PATH
from mcp_servers.osm_server import OSMServer
from mcp_servers.gis_server import GISServer
from mcp_servers.weather_server import WeatherServer
from mcp_servers.zoning_server import ZoningServer
from mcp_servers.demographics_server import DemographicsServer
from tools.utility import UtilityServer

try:
    from shapely.geometry import shape as _shape
except ImportError:
    _shape = None

router = APIRouter()

_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
_MODEL_CONFIG_PATH = _BACKEND_DIR / "model_config.json"
_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _get_model() -> str:
    try:
        data = json.loads(_MODEL_CONFIG_PATH.read_text())
        return data.get("model") or _DEFAULT_MODEL
    except Exception:
        return _DEFAULT_MODEL

_servers = {
    "osm": OSMServer(),
    "gis": GISServer(),
    "weather": WeatherServer(),
    "zoning": ZoningServer(),
    "demographics": DemographicsServer(),
    "utility": UtilityServer(db_path=DB_PATH),
}

# ── Action tool names (sent directly to frontend as map actions) ──────────────

_ACTION_TOOLS = {
    "fly_to", "fit_bounds",
    "add_marker", "add_markers", "clear_markers",
    "draw_line", "draw_polygon", "draw_circle", "add_geojson",
    "highlight_features", "set_layer_style", "toggle_layer", "remove_layer",
    "save_bookmark", "go_to_bookmark", "export_region_clip",
}

# ── System prompt ─────────────────────────────────────────────────────────────

DOCUMENT_SYSTEM_PROMPT = (
    "You are an expert urban planning analyst. The user has shared a map image or planning document with you. "
    "Carefully analyze what you see: land use patterns, zoning areas, transportation networks, "
    "infrastructure, built vs. open spaces, density patterns, boundaries, and any labels or legends. "
    "Answer questions thoroughly with professional planning insights. "
    "You may save detailed analyses using the create_artifact tool."
)

SYSTEM_PROMPT = (
    "You are an expert urban planning assistant embedded in a desktop GIS application. "
    "You help with zoning analysis, land use planning, transportation networks, "
    "environmental impact, building codes, community development, and spatial analysis. "
    "Always respond in English regardless of the query language.\n\n"
    "AVAILABLE TOOLS:\n"
    "- Navigate: fly_to, fit_bounds\n"
    "- Markers: add_marker, add_markers, clear_markers\n"
    "- Layers: add_geojson, toggle_layer, remove_layer, set_layer_style\n"
    "- Highlight: highlight_features\n"
    "- Search: web_search, geocode\n"
    "- OSM: osm_search (amenities, buildings, roads), "
    "osm_boundary (city/district/state boundary polygons), "
    "osm_reverse_geocode, osm_route_overview\n"
    "- Weather: get_weather, get_air_quality\n"
    "- GIS: gis_buffer, gis_centroid, gis_area, gis_convex_hull, "
    "gis_point_in_polygon, gis_bounding_box, gis_union\n"
    "- Bookmarks: save_bookmark, go_to_bookmark, export_region_clip\n"
    "- Zoning: analyze_zones, detect_zone_overlaps\n"
    "- Demographics: get_demographics\n"
    "- Artifacts: create_artifact\n\n"
    "MAP CONTEXT:\n"
    "The current map state is appended to every message. It includes:\n"
    "- bounds: current viewport (west,south,east,north) when available.\n"
    "- bookmarks: saved regions; use go_to_bookmark to navigate.\n"
    "- Layer list with geometry_data (actual coordinates for small layers, bbox for large ones).\n\n"
    "IMPORTANT RULES:\n"
    "1. Do NOT add markers unless the user explicitly asks for markers or pins.\n"
    "2. Do NOT repeat a tool call you already made. Call each tool ONCE per distinct item.\n"
    "3. osm_search and osm_boundary results are AUTO-DISPLAYED on the map. "
    "Do NOT call add_geojson for data that was already returned by these tools.\n"
    "4. When using osm_boundary, ALWAYS pass country_code (e.g. 'IN' for India) to avoid wrong matches.\n"
    "5. Only call the tools the user's request requires. Do not add extra actions.\n"
    "6. When the user asks to navigate somewhere, use fly_to. Do not add markers unless asked.\n"
    "7. SUB-CITY BOUNDARIES (sectors, neighborhoods, colonies, suburbs): call osm_boundary with "
    "place_type='suburb' (or 'neighbourhood'/'quarter') and parent='<city>'. Do NOT use admin_level — "
    "Indian sectors are not administrative boundaries in OSM. If a result is empty, KEEP TRYING: "
    "(a) name variants like 'Sector 30 A' / 'Sector 30 B' (Chandigarh sectors are often split), "
    "(b) other place_type values, (c) osm_search(feature_type='place', feature_value='suburb') near "
    "the city center. Do not give up after one failed call.\n"
    "8. When finished, stop calling tools and respond with a brief summary of what you did."
)

# ── Build OpenAI tool definitions ─────────────────────────────────────────────

def _decl_to_openai(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def _build_tools() -> list[dict]:
    tools = []

    # Action tools
    action_defs = [
        ("fly_to", "Animate the map to specific coordinates", {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lng": {"type": "number"},
                "zoom": {"type": "number", "description": "Zoom level 1-20, default 15"},
            },
            "required": ["lat", "lng"],
        }),
        ("fit_bounds", "Fit the map view to a bounding box", {
            "type": "object",
            "properties": {
                "south": {"type": "number"}, "west": {"type": "number"},
                "north": {"type": "number"}, "east": {"type": "number"},
            },
            "required": ["south", "west", "north", "east"],
        }),
        ("add_marker", "Add a labeled marker pin on the map", {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lng": {"type": "number"},
                "label": {"type": "string"}, "color": {"type": "string"},
            },
            "required": ["lat", "lng", "label"],
        }),
        ("add_markers", "Add multiple markers at once", {
            "type": "object",
            "properties": {
                "markers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"}, "lng": {"type": "number"},
                            "label": {"type": "string"}, "color": {"type": "string"},
                        },
                        "required": ["lat", "lng", "label"],
                    },
                },
            },
            "required": ["markers"],
        }),
        ("clear_markers", "Remove all AI-placed markers from the map", {
            "type": "object", "properties": {},
        }),
        ("add_geojson", "Add a GeoJSON FeatureCollection as a new map layer", {
            "type": "object",
            "properties": {
                "geojson": {"type": "object", "description": "A GeoJSON FeatureCollection"},
                "name": {"type": "string"}, "color": {"type": "string"},
            },
            "required": ["geojson", "name"],
        }),
        ("highlight_features", "Highlight features in a loaded layer by a property value", {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"},
                "property_name": {"type": "string"},
                "property_value": {"type": "string"},
            },
            "required": ["layer_name", "property_name", "property_value"],
        }),
        ("set_layer_style", "Change the visual style of a loaded map layer", {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"}, "fill_color": {"type": "string"},
                "line_color": {"type": "string"}, "opacity": {"type": "number"},
            },
            "required": ["layer_name"],
        }),
        ("toggle_layer", "Show or hide a map layer", {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"}, "visible": {"type": "boolean"},
            },
            "required": ["layer_name", "visible"],
        }),
        ("remove_layer", "Remove a layer from the map entirely", {
            "type": "object",
            "properties": {"layer_name": {"type": "string"}},
            "required": ["layer_name"],
        }),
        ("save_bookmark", "Save the current map region as a named bookmark", {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "south": {"type": "number"}, "west": {"type": "number"},
                "north": {"type": "number"}, "east": {"type": "number"},
                "zoom": {"type": "number"},
            },
            "required": ["name"],
        }),
        ("go_to_bookmark", "Fly the map to a previously saved bookmark by name", {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }),
        ("export_region_clip", "Clip all loaded layers to a bounding box and save as GeoJSON", {
            "type": "object",
            "properties": {
                "output_base_name": {"type": "string"},
                "south": {"type": "number"}, "west": {"type": "number"},
                "north": {"type": "number"}, "east": {"type": "number"},
            },
            "required": ["output_base_name"],
        }),
    ]
    for name, desc, params in action_defs:
        tools.append(_decl_to_openai(name, desc, params))

    # MCP server tools (utility tools come from UtilityServer in _servers)
    for srv in _servers.values():
        for decl in srv.get_declarations():
            tools.append(_decl_to_openai(decl.name, decl.description, decl.parameters))

    return tools


_TOOLS = _build_tools()

# ── Tool execution ────────────────────────────────────────────────────────────

async def _send_action(ws: WebSocket, action: str, payload: dict) -> None:
    await ws.send_text(json.dumps({"type": "action", "action": action, "payload": payload}))


async def _execute_tool(name: str, args: dict, ws: WebSocket) -> str:
    # Map action tools → send directly to frontend
    if name in _ACTION_TOOLS:
        await _send_action(ws, name, args)
        return json.dumps({"status": "success", "message": f"'{name}' executed on map."})

    # MCP server tools (includes UtilityServer)
    for srv in _servers.values():
        if name in srv.tool_names:
            result = await srv.execute(name, args)

            # Side-effect: refresh artifacts panel after a successful create_artifact
            if name == "create_artifact":
                await _send_action(ws, "refresh_artifacts", {})
                return json.dumps(result)

            # Auto-display osm_search result on map
            if name == "osm_search" and "geojson" in result and result.get("count", 0) > 0:
                label = f"{args.get('feature_value', 'features')} ({args.get('feature_type', '')})"
                await _send_action(ws, "add_geojson", {"geojson": result["geojson"], "name": label})
                features_summary = []
                for f in result["geojson"].get("features", [])[:50]:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    entry = {"name": props.get("name", "")}
                    if geom.get("type") == "Point":
                        entry["lat"] = geom["coordinates"][1]
                        entry["lng"] = geom["coordinates"][0]
                    features_summary.append(entry)
                result = {
                    "count": result["count"],
                    "displayed_on_map": True,
                    "features": features_summary,
                }

            # Auto-display osm_boundary on map. Keep geometry/centroid/bbox in
            # the model-visible result so follow-up tools (gis_area, gis_buffer,
            # gis_point_in_polygon) can chain on the boundary.
            elif name == "osm_boundary" and "geojson" in result:
                label = f"{args.get('name', 'Boundary')} boundary"
                await _send_action(ws, "add_geojson", {"geojson": result["geojson"], "name": label})
                model_result: dict = {
                    "name": result.get("name", ""),
                    "displayed_on_map": True,
                    "layer_name": label,
                }
                feats = result["geojson"].get("features") or []
                geom = feats[0].get("geometry") if feats else None
                if geom and _shape is not None:
                    try:
                        g = _shape(geom)
                        if not g.is_empty:
                            minx, miny, maxx, maxy = g.bounds
                            c = g.centroid
                            model_result["centroid"] = {"lat": round(c.y, 6), "lng": round(c.x, 6)}
                            model_result["bbox"] = {
                                "south": round(miny, 6), "west": round(minx, 6),
                                "north": round(maxy, 6), "east": round(maxx, 6),
                            }
                    except Exception:
                        pass
                if geom:
                    model_result["geometry"] = geom
                result = model_result

            # Auto-display route
            elif name == "osm_route_overview" and "geometry" in result:
                await _send_action(ws, "draw_line", {
                    "coordinates": result["geometry"]["coordinates"],
                    "color": "#2563eb", "width": 4,
                    "label": f"Route ({result.get('distance_km', '?')} km)",
                })

            # Auto-display buffer/hull/union
            elif name in ("gis_buffer", "gis_convex_hull", "gis_union") and "geojson" in result:
                label = {"gis_buffer": f"Buffer ({args.get('radius_meters', '?')}m)",
                         "gis_convex_hull": "Convex Hull", "gis_union": "Union"}[name]
                await _send_action(ws, "add_geojson", {
                    "geojson": {"type": "FeatureCollection", "features": [result["geojson"]]},
                    "name": label,
                })

            return json.dumps(result)

    return json.dumps({"error": f"Unknown tool: {name}"})


# ── Agentic loop ──────────────────────────────────────────────────────────────

async def _run_agent(messages: list[dict], ws: WebSocket, tools: list[dict] | None = None) -> None:
    """Run the tool-calling loop until the model stops calling tools or errors."""
    if tools is None:
        tools = _TOOLS
    max_rounds = 10

    for _ in range(max_rounds):
        accumulated_text = ""
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = None

        try:
            stream = await _client.chat.completions.create(
                model=_get_model(),
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                stream=True,
                timeout=60,
            )

            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue

                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason

                # Stream text to frontend
                if delta.content:
                    accumulated_text += delta.content
                    await ws.send_text(json.dumps({"type": "stream", "content": delta.content}))

                # Accumulate tool call deltas
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc.function.arguments

        except Exception as e:
            await ws.send_text(json.dumps({
                "type": "error",
                "code": _classify_error(e),
                "message": str(e),
            }))
            break

        # Add assistant message to history
        assistant_msg: dict = {"role": "assistant"}
        if accumulated_text:
            assistant_msg["content"] = accumulated_text
        else:
            assistant_msg["content"] = None
        if tool_calls_acc:
            assistant_msg["tool_calls"] = [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in tool_calls_acc.values()
            ]
        messages.append(assistant_msg)

        # If no tool calls, we're done. Tool calls MUST be answered even if
        # finish_reason == "stop" — leaving them unanswered breaks the next turn.
        if not tool_calls_acc:
            break

        # Execute tool calls and collect results
        for tc in tool_calls_acc.values():
            tool_name = tc["name"]
            args_raw = tc["arguments"] or ""
            try:
                args = json.loads(args_raw) if args_raw else {}
                args_error = None
            except json.JSONDecodeError as e:
                args = {}
                args_error = str(e)

            await ws.send_text(json.dumps({"type": "tool_use", "tool": tool_name, "args": args}))

            if args_error:
                # Streaming was interrupted; return a structured error so the
                # tool_call_id has a matching tool message and the next turn
                # is well-formed.
                result_str = json.dumps({
                    "error": "Arguments could not be parsed; streaming was interrupted.",
                    "detail": args_error,
                })
            else:
                result_str = await _execute_tool(tool_name, args, ws)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_str,
            })

        if finish_reason == "stop":
            break


# ── WebSocket handler ─────────────────────────────────────────────────────────

@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()

    # Persistent message history for this connection
    messages: list[dict] = []

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            user_content = payload.get("content", "")
            map_context = payload.get("map_context")
            image_data = payload.get("image")  # {base64, mime_type} or None
            history_payload = payload.get("history")

            if not user_content.strip():
                continue

            # Renderer can replay prior conversation on reconnect/model-switch
            # by passing `history`: a list of {role, content} pairs.
            if isinstance(history_payload, list):
                replayed: list[dict] = []
                for m in history_payload:
                    role = m.get("role")
                    content = m.get("content")
                    if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                        replayed.append({"role": role, "content": content})
                messages = replayed

            is_document_mode = image_data is not None

            if is_document_mode:
                system = DOCUMENT_SYSTEM_PROMPT
                # Document mode now bridges to the live map: model can fly_to,
                # add markers, run osm_search, save artifacts. Map context is
                # included when supplied.
                if map_context:
                    system += f"\n\nCurrent map state:\n{json.dumps(map_context, indent=2)}"
                tools = _TOOLS
                # Build vision message
                user_msg: dict = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_content},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{image_data['mime_type']};base64,{image_data['base64']}"
                        }},
                    ],
                }
            else:
                system = SYSTEM_PROMPT
                if map_context:
                    system += f"\n\nCurrent map state:\n{json.dumps(map_context, indent=2)}"
                tools = _TOOLS
                user_msg = {"role": "user", "content": user_content}

            full_messages = [{"role": "system", "content": system}] + messages
            full_messages.append(user_msg)

            await _run_agent(full_messages, websocket, tools=tools)

            # Persist exchange into history, but strip system + image data (keep history lean)
            new_history = []
            for m in full_messages:
                if m["role"] == "system":
                    continue
                if isinstance(m.get("content"), list):
                    # Strip image parts from stored history to save memory
                    text_parts = [p["text"] for p in m["content"] if p.get("type") == "text"]
                    new_history.append({"role": m["role"], "content": " ".join(text_parts)})
                else:
                    new_history.append(m)
            messages = new_history

            await websocket.send_text(json.dumps({"type": "end"}))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({
                "type": "error", "code": _classify_error(e), "message": str(e),
            }))
            await websocket.send_text(json.dumps({"type": "end"}))
        except Exception:
            pass


def _classify_error(e: Exception) -> str:
    """Map an exception to a short error code the UI can style on."""
    msg = str(e).lower()
    name = type(e).__name__
    if "api key" in msg or "openai_api_key" in msg or "401" in msg or name == "AuthenticationError":
        return "auth"
    if "429" in msg or "rate limit" in msg or name == "RateLimitError":
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg or name == "APITimeoutError":
        return "timeout"
    if "connection" in msg or name in ("APIConnectionError", "ConnectionError"):
        return "connection"
    if "404" in msg or "not found" in msg:
        return "not_found"
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return "upstream"
    return "internal"
