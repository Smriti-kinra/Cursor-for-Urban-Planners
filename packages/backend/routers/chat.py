"""
Chat router — thin WebSocket bridge to opencode.

Responsibilities:
  1. Accept WebSocket connections from the frontend.
  2. Create an opencode session per connection and forward user messages.
  3. Subscribe to opencode's SSE event stream and relay text/tool events back.
  4. Expose POST /internal/action so the MCP bridge can push map actions to
     the active frontend WebSocket (single-user desktop app assumption).
"""

import asyncio
import json
import os

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter()

OPENCODE_URL = os.environ.get("OPENCODE_URL", "http://localhost:4096")

SYSTEM_PROMPT = (
    "You are an expert urban planning assistant embedded in a desktop GIS application. "
    "You help with zoning analysis, land use planning, transportation networks, "
    "environmental impact, building codes, community development, and spatial analysis. "
    "Always respond in English regardless of the query language.\n\n"
    "AVAILABLE TOOLS (all prefixed with urban_):\n"
    "- Navigate: urban_fly_to, urban_fit_bounds\n"
    "- Markers: urban_add_marker, urban_add_markers, urban_clear_markers\n"
    "- Draw: urban_draw_line, urban_draw_polygon, urban_draw_circle\n"
    "- Layers: urban_add_geojson, urban_toggle_layer, urban_remove_layer, urban_set_layer_style\n"
    "- Highlight: urban_highlight_features\n"
    "- Measure: urban_measure_distance, urban_measure_area\n"
    "- Search: urban_web_search, urban_geocode\n"
    "- OSM: urban_osm_search (amenities, buildings, roads), "
    "urban_osm_boundary (city/district/state boundary polygons), "
    "urban_osm_reverse_geocode, urban_osm_route_overview\n"
    "- Weather: urban_get_weather, urban_get_air_quality\n"
    "- GIS: urban_gis_buffer, urban_gis_centroid, urban_gis_area, urban_gis_convex_hull, "
    "urban_gis_point_in_polygon, urban_gis_bounding_box, urban_gis_union\n"
    "- Bookmarks: urban_save_bookmark, urban_go_to_bookmark, urban_export_region_clip\n"
    "- Zoning: urban_analyze_zones, urban_detect_zone_overlaps\n"
    "- Demographics: urban_get_demographics\n"
    "- Artifacts: urban_create_artifact\n\n"
    "MAP CONTEXT:\n"
    "The current map state is appended to every message. It includes:\n"
    "- bounds: current viewport (west,south,east,north) when available.\n"
    "- bookmarks: saved regions; use go_to_bookmark to navigate.\n"
    "- Layer list with geometry_data (actual coordinates for small layers, bbox for large ones).\n\n"
    "IMPORTANT RULES:\n"
    "1. Do NOT add markers unless the user explicitly asks for markers or pins.\n"
    "2. Do NOT repeat a tool call you already made. Call each tool ONCE per distinct item.\n"
    "3. urban_osm_search and urban_osm_boundary results are AUTO-DISPLAYED on the map. "
    "Do NOT call urban_add_geojson for data that was already returned by these tools.\n"
    "4. When using urban_osm_boundary, ALWAYS pass country_code (e.g. 'IN' for India) to avoid wrong matches.\n"
    "5. Only call the tools the user's request requires. Do not add extra actions.\n"
    "6. When the user asks to navigate somewhere, use urban_fly_to. Do not add markers unless asked.\n"
    "7. When finished, stop calling tools and respond with a brief summary of what you did."
)

# The most recently active WebSocket connection (single-user desktop app).
_active_ws: WebSocket | None = None


# ── Internal action relay ─────────────────────────────────────────────────────

@router.post("/internal/action")
async def internal_action(request: Request):
    """Receive an action from the MCP bridge and forward it to the frontend."""
    global _active_ws
    body = await request.json()
    if _active_ws is not None:
        try:
            await _active_ws.send_text(json.dumps({
                "type": "action",
                "action": body.get("action"),
                "payload": body.get("payload", {}),
            }))
        except Exception:
            _active_ws = None
    return {"ok": True}


# ── opencode session helpers ──────────────────────────────────────────────────

async def _create_session() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{OPENCODE_URL}/session",
                json={"title": "Urban Planning"},
            )
            resp.raise_for_status()
            return resp.json()["id"]
    except Exception:
        return None


async def _send_message(session_id: str, text: str, system: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{OPENCODE_URL}/session/{session_id}/prompt_async",
                json={
                    "system": system,
                    "parts": [{"type": "text", "text": text}],
                },
            )
            return resp.status_code == 204
    except Exception:
        return False


async def _stream_until_idle(session_id: str, websocket: WebSocket) -> None:
    """Subscribe to opencode SSE and relay events to the frontend until the session goes idle."""
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", f"{OPENCODE_URL}/event") as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    props = event.get("properties", {})

                    # Filter to events belonging to this session
                    if props.get("sessionID") != session_id:
                        continue

                    etype = event.get("type", "")

                    if etype == "message.part.delta":
                        # Streaming text delta
                        if props.get("field") == "text":
                            delta = props.get("delta", "")
                            if delta:
                                await websocket.send_text(json.dumps({
                                    "type": "stream", "content": delta,
                                }))

                    elif etype == "message.part.updated":
                        part = props.get("part", {})

                        # Tool invocation notification
                        if part.get("type") == "tool":
                            state = part.get("state", {})
                            if state.get("status") == "running":
                                await websocket.send_text(json.dumps({
                                    "type": "tool_use",
                                    "tool": part.get("tool", ""),
                                    "args": state.get("input", {}),
                                }))

                    elif etype == "session.idle":
                        await websocket.send_text(json.dumps({"type": "end"}))
                        return

                    elif etype == "session.error":
                        err = props.get("error", "Unknown error")
                        await websocket.send_text(json.dumps({
                            "type": "stream", "content": f"\n\n[Error: {err}]",
                        }))
                        await websocket.send_text(json.dumps({"type": "end"}))
                        return

    except asyncio.CancelledError:
        raise
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({
                "type": "stream", "content": f"\n\n[Connection error: {e}]",
            }))
            await websocket.send_text(json.dumps({"type": "end"}))
        except Exception:
            pass


# ── WebSocket handler ─────────────────────────────────────────────────────────

@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    global _active_ws
    await websocket.accept()
    _active_ws = websocket

    # Create one opencode session per WebSocket connection
    session_id = await _create_session()
    if session_id is None:
        await websocket.send_text(json.dumps({
            "type": "stream",
            "content": "Could not connect to opencode. Make sure `opencode serve` is running on port 4096.",
        }))
        await websocket.send_text(json.dumps({"type": "end"}))
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            user_content = message.get("content", "")
            map_context = message.get("map_context")

            system = SYSTEM_PROMPT
            if map_context:
                system += f"\n\nCurrent map state:\n{json.dumps(map_context, indent=2)}"

            sent = await _send_message(session_id, user_content, system)
            if not sent:
                await websocket.send_text(json.dumps({
                    "type": "stream",
                    "content": "Failed to send message to opencode.",
                }))
                await websocket.send_text(json.dumps({"type": "end"}))
                continue

            await _stream_until_idle(session_id, websocket)

    except WebSocketDisconnect:
        if _active_ws is websocket:
            _active_ws = None
