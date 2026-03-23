"""
OpenStreetMap MCP Server

Provides tools for querying real-world geographic features via the Overpass API.
Supports amenity search, land-use queries, building footprints, road networks, etc.
"""

from __future__ import annotations

import httpx
from llm.base import ToolDeclaration


class OSMServer:
    description = "OpenStreetMap Overpass API for querying real-world features"
    tool_names = {"osm_search", "osm_reverse_geocode", "osm_route_overview"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="osm_search",
                description=(
                    "Search OpenStreetMap for features near a location. "
                    "Returns GeoJSON displayed on the map automatically. "
                    "Use for amenities (hospitals, schools, parks), "
                    "infrastructure (bus_stop, railway, highway), buildings, land use."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "feature_type": {
                            "type": "string",
                            "description": "OSM tag key: amenity, building, highway, leisure, natural, shop, tourism, landuse, railway, waterway, public_transport",
                        },
                        "feature_value": {
                            "type": "string",
                            "description": "OSM tag value, e.g. hospital, school, park, residential, bus_stop",
                        },
                        "lat": {"type": "number", "description": "Center latitude"},
                        "lng": {"type": "number", "description": "Center longitude"},
                        "radius_meters": {"type": "number", "description": "Search radius in meters (default 1000, max 5000)"},
                    },
                    "required": ["feature_type", "feature_value", "lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="osm_reverse_geocode",
                description="Get address and place details from coordinates",
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude"},
                        "lng": {"type": "number", "description": "Longitude"},
                    },
                    "required": ["lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="osm_route_overview",
                description=(
                    "Get a driving/walking route overview between two points using OSRM. "
                    "Returns distance, duration, and route geometry."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "start_lat": {"type": "number"},
                        "start_lng": {"type": "number"},
                        "end_lat": {"type": "number"},
                        "end_lng": {"type": "number"},
                        "mode": {
                            "type": "string",
                            "description": "Travel mode: driving (default), walking, cycling",
                        },
                    },
                    "required": ["start_lat", "start_lng", "end_lat", "end_lng"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "osm_search":
            return await self._osm_search(args)
        elif tool_name == "osm_reverse_geocode":
            return await self._reverse_geocode(args)
        elif tool_name == "osm_route_overview":
            return await self._route_overview(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _osm_search(self, args: dict) -> dict:
        feature_type = args.get("feature_type", "amenity")
        feature_value = args.get("feature_value", "")
        lat = args.get("lat", 0)
        lng = args.get("lng", 0)
        radius = min(int(args.get("radius_meters", 1000)), 5000)

        overpass_query = f"""
[out:json][timeout:25];
(
  node["{feature_type}"="{feature_value}"](around:{radius},{lat},{lng});
  way["{feature_type}"="{feature_value}"](around:{radius},{lat},{lng});
  relation["{feature_type}"="{feature_value}"](around:{radius},{lat},{lng});
);
out body;
>;
out skel qt;
"""
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.post(
                    "https://overpass-api.de/api/interpreter",
                    data={"data": overpass_query},
                )
                data = resp.json()

            nodes: dict[int, tuple[float, float]] = {}
            features = []
            for el in data.get("elements", []):
                if el["type"] == "node":
                    nodes[el["id"]] = (el.get("lon", 0), el.get("lat", 0))
                    if el.get("tags"):
                        features.append({
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                            "properties": {**el.get("tags", {}), "osm_id": el["id"]},
                        })
                elif el["type"] == "way" and el.get("tags"):
                    coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
                    if len(coords) >= 2:
                        geom_type = "Polygon" if coords[0] == coords[-1] and len(coords) >= 4 else "LineString"
                        geom = {"type": geom_type, "coordinates": [coords] if geom_type == "Polygon" else coords}
                        features.append({
                            "type": "Feature",
                            "geometry": geom,
                            "properties": {**el.get("tags", {}), "osm_id": el["id"]},
                        })

            geojson = {"type": "FeatureCollection", "features": features}
            return {
                "geojson": geojson,
                "count": len(features),
                "feature_type": feature_type,
                "feature_value": feature_value,
            }
        except Exception as e:
            return {"error": str(e)}

    async def _reverse_geocode(self, args: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                resp = await http.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={
                        "lat": args["lat"],
                        "lon": args["lng"],
                        "format": "json",
                        "addressdetails": 1,
                        "zoom": 18,
                    },
                    headers={"User-Agent": "CursorUrbanPlanners/1.0"},
                )
                data = resp.json()
                return {
                    "display_name": data.get("display_name", ""),
                    "address": data.get("address", {}),
                    "type": data.get("type", ""),
                    "osm_type": data.get("osm_type", ""),
                }
        except Exception as e:
            return {"error": str(e)}

    async def _route_overview(self, args: dict) -> dict:
        mode_map = {"driving": "car", "walking": "foot", "cycling": "bike"}
        mode = mode_map.get(args.get("mode", "driving"), "car")
        start = f"{args['start_lng']},{args['start_lat']}"
        end = f"{args['end_lng']},{args['end_lat']}"

        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(
                    f"https://router.project-osrm.org/route/v1/{mode}/{start};{end}",
                    params={"overview": "full", "geometries": "geojson", "steps": "false"},
                )
                data = resp.json()
                if data.get("code") != "Ok" or not data.get("routes"):
                    return {"error": data.get("message", "No route found")}

                route = data["routes"][0]
                return {
                    "distance_km": round(route["distance"] / 1000, 2),
                    "duration_minutes": round(route["duration"] / 60, 1),
                    "geometry": route["geometry"],
                }
        except Exception as e:
            return {"error": str(e)}
