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
from mcp_servers.overture_server import OvertureServer
from mcp_servers.google_places_server import GooglePlacesServer
from mcp_servers.google_environment_server import GoogleEnvironmentServer
from tools.utility import UtilityServer
from tools.config import get_model as _get_model

try:
    from shapely.geometry import shape as _shape
except ImportError:
    _shape = None

router = APIRouter()

_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

_servers = {
    "osm": OSMServer(),
    "gis": GISServer(),
    "weather": WeatherServer(),
    "zoning": ZoningServer(),
    "demographics": DemographicsServer(),
    "overture": OvertureServer(),
    "google_places": GooglePlacesServer(),
    "google_env": GoogleEnvironmentServer(),
    "utility": UtilityServer(db_path=DB_PATH),
}

# ── Action tool names (sent directly to frontend as map actions) ──────────────

_ACTION_TOOLS = {
    "fly_to", "fit_bounds", "add_marker", "add_markers", "clear_markers",
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
    "osm_boundary_union (merge multiple boundaries into ONE polygon — server-side, no coordinate echoing), "
    "osm_reverse_geocode, osm_route_overview\n"
    "- Google Places (PREFER for commercial POIs — fresher and brand-named): "
    "places_autocomplete, place_details, nearby_places, "
    "nearby_places_in_polygon (polygon-clipped), places_density\n"
    "- Overture Maps (fallback for places; building footprints): "
    "overture_places_search, overture_buildings_search\n"
    "- Google Environment: get_elevation (terrain), get_air_quality_google "
    "(per-pollutant), get_solar_building (rooftop solar potential)\n"
    "- Weather: get_weather, get_air_quality (Open-Meteo fallback)\n"
    "- GIS: gis_buffer, gis_centroid, gis_area, gis_convex_hull, "
    "gis_point_in_polygon, gis_bounding_box, gis_union\n"
    "- Bookmarks: save_bookmark, go_to_bookmark, export_region_clip\n"
    "- Zoning: analyze_zones, detect_zone_overlaps\n"
    "- Demographics: get_demographics\n"
    "- Artifacts: create_artifact (format: markdown/table/geojson), list_artifacts, get_artifact\n"
    "  Re-adding geometry: call get_artifact to retrieve a geojson artifact's content, then pass it to add_geojson.\n"
    "- Reports: generate_report — generates a deep research urban planning report using web search. "
    "Use when user asks to generate/create/write a report or planning analysis.\n\n"
    "MAP CONTEXT:\n"
    "The current map state is appended to every message. It includes:\n"
    "- bounds: current viewport (west,south,east,north) when available.\n"
    "- bookmarks: saved regions; use go_to_bookmark to navigate.\n"
    "- Layer list with geometry_data (actual coordinates for small layers, bbox for large ones).\n\n"
    "IMPORTANT RULES:\n"
    "1. Do NOT add markers unless the user explicitly asks for markers or pins.\n"
    "2. Do NOT repeat a tool call you already made. Call each tool ONCE per distinct item.\n"
    "3. osm_search, osm_boundary, overture_places_search, overture_buildings_search, "
    "nearby_places, and nearby_places_in_polygon results are AUTO-DISPLAYED on the map. "
    "Do NOT call add_geojson for data that was already returned by these tools. For "
    "COMMERCIAL POIs (restaurants, hotels, retail, services, schools, hospitals) PREFER "
    "nearby_places (Google) — it has the freshest brand names and category data. When the "
    "user asks for POIs INSIDE a drawn polygon / region / sector boundary (any non-circular "
    "area), use nearby_places_in_polygon — it returns only places that fall within the "
    "polygon. Use overture_places_search only when the Google tools return empty or "
    "upstream_unavailable. Use osm_search for non-commercial OSM-tagged features (water, "
    "infrastructure, hand-mapped local data).\n"
    "4. When using osm_boundary, ALWAYS pass country_code (e.g. 'IN' for India) to avoid wrong matches.\n"
    "5. Only call the tools the user's request requires. Do not add extra actions.\n"
    "6. When the user asks to navigate somewhere, use fly_to. Do not add markers unless asked.\n"
    "7. SUB-CITY BOUNDARIES (sectors, neighborhoods, colonies, suburbs): call osm_boundary with "
    "place_type='suburb' (or 'neighbourhood'/'quarter') and parent='<city>'. Do NOT use admin_level — "
    "Indian sectors are not administrative boundaries in OSM. If a result is empty, KEEP TRYING: "
    "(a) name variants like 'Sector 30 A' / 'Sector 30 B' (Chandigarh sectors are often split), "
    "(b) other place_type values, (c) osm_search(feature_type='place', feature_value='suburb') near "
    "the city center. Do not give up after one failed call.\n"
    "8. When finished, stop calling tools and respond with a brief summary of what you did.\n"
    "9. SINGLE POLYGON ACROSS MULTIPLE PLACES: when the user asks for ONE polygon/region/boundary "
    "spanning multiple cities/districts/sectors (e.g. 'mark Chandigarh, Panchkula and Mohali as one "
    "polygon', 'tricity area', 'merge X and Y'), call osm_boundary_union with all places in a single "
    "call. Do NOT call osm_boundary multiple times and then try gis_union — gis_union requires you to "
    "echo every coordinate as arguments, which is slow and unreliable.\n"
    "10. AIR QUALITY: prefer get_air_quality_google (per-pollutant breakdown, AQI, health "
    "recommendations). Fall back to get_air_quality (Open-Meteo) only if Google returns "
    "upstream_unavailable.\n"
    "11. AMBIGUOUS PLACE NAMES: if the user types a partial or ambiguous place name, call "
    "places_autocomplete first to get candidate place_ids, then place_details on the best match "
    "to resolve to coordinates. Skip this for unambiguous queries — geocode is faster."
)

# ── Deep research helpers ──────────────────────────────────────────────────────

_RESEARCH_SYSTEM = (
    "You are a professional urban planning report writer. "
    "Generate a well-structured, data-driven report in clean Markdown. "
    "Use the provided conversation, map data, and artifacts as your primary source. "
    "Enrich your analysis with publicly available information about the location. "
    "Respond ONLY with the Markdown report. Always respond in English."
)

_RESEARCH_REPORT_TEMPLATE = """Generate a comprehensive urban planning report based on the data below.

Structure the report with these sections:

# Urban Planning Report

## Executive Summary
(2-3 paragraph overview of the planning discussion, location, and key findings)

## Site Analysis
(Geographic context, existing conditions, basemap and layer data, drawn features, placed markers)

## Key Findings
(Main points from the conversation and analysis, enriched with current public data)

## Recommendations
(Actionable next steps based on the discussion and research)

## Appendix
(Data sources, layer descriptions, methodology notes, web sources consulted)

Be specific and professional. Reference the actual map data, drawn geometries, and conversation details provided.

---
"""


def _build_research_prompt(messages: list[dict], map_context: dict | None) -> str:
    """Build the deep research prompt from conversation history and map context."""
    parts = [_RESEARCH_REPORT_TEMPLATE]

    if map_context:
        center = map_context.get("center", [])
        zoom = map_context.get("zoom", "")
        bounds = map_context.get("bounds", {})
        basemap = map_context.get("basemap", "")
        bookmarks = map_context.get("bookmarks", [])
        layers = map_context.get("layers", [])

        loc_lines = [f"**Center:** {center}", f"**Zoom:** {zoom}", f"**Basemap:** {basemap}"]
        if bounds:
            loc_lines.append(
                f"**Bounds:** W={bounds.get('west')}, S={bounds.get('south')}, "
                f"E={bounds.get('east')}, N={bounds.get('north')}"
            )
        parts.append("## Map Context\n" + "\n".join(loc_lines))

        if bookmarks:
            bm_lines = [
                f"- {b.get('name', '')}: bounds W={b.get('west')}, S={b.get('south')}, "
                f"E={b.get('east')}, N={b.get('north')}"
                for b in bookmarks
            ]
            parts.append("### Bookmarks\n" + "\n".join(bm_lines))

        if layers:
            layer_lines = []
            for layer in layers:
                name = layer.get("name", "unnamed")
                count = layer.get("featureCount", 0)
                geom_types = ", ".join(layer.get("geometryTypes", []))
                props = ", ".join(layer.get("properties", []))
                visible = layer.get("visible", True)
                line = f"- **{name}** ({count} features, {geom_types}, visible={visible})"
                if props:
                    line += f"\n  Properties: {props}"
                geo = layer.get("geometry_data")
                if geo:
                    if isinstance(geo, list):
                        line += f"\n  Coordinates: {json.dumps(geo)}"
                    elif isinstance(geo, dict) and "bbox" in geo:
                        line += f"\n  Bounding box: {geo['bbox']}"
                layer_lines.append(line)
            parts.append("### Layers\n" + "\n".join(layer_lines))

    # Include conversation (skip system and tool messages)
    conv_lines = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "user" and isinstance(content, str) and content.strip():
            conv_lines.append(f"**User:** {content}")
        elif role == "assistant" and isinstance(content, str) and content.strip():
            conv_lines.append(f"**Assistant:** {content}")
    if conv_lines:
        parts.append("## Conversation\n" + "\n\n".join(conv_lines))

    return "\n\n".join(parts)


async def _run_deep_research(messages: list[dict], map_context: dict | None, ws: WebSocket) -> str:
    """Run o4-mini-deep-research and stream progress back over the WebSocket.

    Sends these WS message types:
      research_start  — emitted once before the API call
      research_step   — one per web search (query string)
      research_report — final markdown text + citations list
      research_done   — terminal signal

    Returns a short result string for the tool message inserted into history.
    """
    await ws.send_text(json.dumps({"type": "research_start"}))

    prompt = _build_research_prompt(messages, map_context)

    try:
        got_text = False
        async with await _client.responses.create(
            model="o4-mini-deep-research",
            input=prompt,
            instructions=_RESEARCH_SYSTEM,
            tools=[{"type": "web_search_preview"}],
            max_tool_calls=30,
            stream=True,
        ) as stream:
            async for event in stream:
                event_type = getattr(event, "type", None)

                if event_type == "response.web_search_call.searching":
                    query = getattr(event, "query", "") or ""
                    if query:
                        await ws.send_text(json.dumps({
                            "type": "research_step",
                            "query": query,
                        }))

                elif event_type == "response.output_text.done":
                    text = getattr(event, "text", "") or ""
                    if text:
                        got_text = True
                        annotations = []
                        for item in getattr(event, "annotations", None) or []:
                            url = getattr(item, "url", None)
                            title = getattr(item, "title", None)
                            if url:
                                annotations.append({"url": url, "title": title or url})
                        await ws.send_text(json.dumps({
                            "type": "research_report",
                            "markdown": text,
                            "citations": annotations,
                        }))

        if not got_text:
            await ws.send_text(json.dumps({
                "type": "error",
                "code": "research_empty",
                "message": "Deep research completed but produced no report text.",
            }))
            return json.dumps({"error": "No report text produced."})

        await ws.send_text(json.dumps({"type": "research_done"}))
        return json.dumps({"status": "report_generated"})

    except Exception as exc:
        await ws.send_text(json.dumps({
            "type": "error",
            "code": "research_error",
            "message": str(exc),
        }))
        return json.dumps({"error": str(exc)})


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

    # Deep research report generation
    tools.append(_decl_to_openai(
        "generate_report",
        (
            "Generate a comprehensive urban planning research report for the current project. "
            "Use this when the user asks to generate a report, create a report, write a planning report, "
            "or produce a deep research analysis. The report uses web search to enrich the analysis "
            "with current public data. This takes several minutes."
        ),
        {"type": "object", "properties": {}, "required": []},
    ))

    return tools


_TOOLS = _build_tools()

# ── Tool execution ────────────────────────────────────────────────────────────

async def _send_action(ws: WebSocket, action: str, payload: dict) -> None:
    await ws.send_text(json.dumps({"type": "action", "action": action, "payload": payload}))


async def _execute_tool(
    name: str,
    args: dict,
    ws: WebSocket,
    messages: list[dict] | None = None,
    map_context: dict | None = None,
) -> str:
    if name == "generate_report":
        return await _run_deep_research(messages or [], map_context, ws)

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

            # Auto-display overture_places_search and overture_buildings_search
            elif name in ("overture_places_search", "overture_buildings_search") \
                    and "geojson" in result and result.get("count", 0) > 0:
                if name == "overture_places_search":
                    label = f"Overture: {args.get('category') or args.get('query') or 'places'}"
                else:
                    label = "Overture: buildings"
                await _send_action(ws, "add_geojson", {"geojson": result["geojson"], "name": label})
                features_summary = []
                for f in result["geojson"].get("features", [])[:50]:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    entry = {"name": props.get("name", "") or props.get("id", "")}
                    if "category" in props:
                        entry["category"] = props["category"]
                    if "height" in props and props["height"] is not None:
                        entry["height_m"] = props["height"]
                    if geom.get("type") == "Point":
                        entry["lat"] = geom["coordinates"][1]
                        entry["lng"] = geom["coordinates"][0]
                    features_summary.append(entry)
                result = {
                    "count": result["count"],
                    "displayed_on_map": True,
                    "features": features_summary,
                }

            # Auto-display nearby_places (Google) — same shape as Overture, so
            # the trim/summarize step mirrors that branch. Also covers the
            # polygon-clipped variant.
            elif name in ("nearby_places", "nearby_places_in_polygon") \
                    and "geojson" in result and result.get("count", 0) > 0:
                types_label = ",".join(args.get("included_types") or []) or "places"
                suffix = " (in polygon)" if name == "nearby_places_in_polygon" else ""
                label = f"Google: {types_label}{suffix}"
                await _send_action(ws, "add_geojson", {"geojson": result["geojson"], "name": label})
                features_summary = []
                for f in result["geojson"].get("features", [])[:50]:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    entry = {
                        "name": props.get("name", "") or props.get("id", ""),
                        "primary_type": props.get("primary_type"),
                        "address": props.get("address"),
                    }
                    if geom.get("type") == "Point":
                        entry["lat"] = geom["coordinates"][1]
                        entry["lng"] = geom["coordinates"][0]
                    features_summary.append(entry)
                trimmed = {
                    "count": result["count"],
                    "displayed_on_map": True,
                    "features": features_summary,
                }
                # Preserve polygon-clip meta so the LLM can warn when the
                # bounding-circle was capped or when filtering dropped many.
                for k in ("truncated_search", "upstream_count", "search_radius_meters", "centroid"):
                    if k in result:
                        trimmed[k] = result[k]
                result = trimmed

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

            # Auto-display merged boundary union. Only the summary (centroid,
            # bbox, area, place lists) goes back to the model — the merged
            # geometry can be huge and is already on the map as a layer.
            elif name == "osm_boundary_union" and "geojson" in result:
                label = result.get("name") or args.get("layer_name") or "Merged region"
                await _send_action(ws, "add_geojson", {"geojson": result["geojson"], "name": label})
                model_result: dict = {
                    "name": label,
                    "displayed_on_map": True,
                    "layer_name": label,
                    "places_resolved": result.get("places_resolved", []),
                    "places_failed": result.get("places_failed", []),
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
                    try:
                        from tools.geo import area_breakdown
                        model_result["area"] = area_breakdown(geom)
                    except Exception:
                        pass
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

async def _run_agent(
    messages: list[dict],
    ws: WebSocket,
    tools: list[dict] | None = None,
    map_context: dict | None = None,
) -> None:
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
                result_str = await _execute_tool(tool_name, args, ws, messages=messages, map_context=map_context)
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

            await _run_agent(full_messages, websocket, tools=tools, map_context=map_context)

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
