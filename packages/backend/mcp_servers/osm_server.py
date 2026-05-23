"""
OpenStreetMap MCP Server

Provides tools for querying real-world geographic features via the Overpass API.
Supports amenity search, land-use queries, building footprints, road networks, etc.
"""

from __future__ import annotations

import httpx
from llm.base import ToolDeclaration


def _merge_ways(way_coords: list[list[list[float]]]) -> list[list[list[float]]]:
    """Merge an unordered list of way coordinate arrays into closed rings.

    Overpass returns boundary relations as individual way segments that
    need to be joined end-to-end to form complete polygon rings.
    """
    if not way_coords:
        return []

    remaining = [list(w) for w in way_coords]
    rings: list[list[list[float]]] = []

    while remaining:
        current = remaining.pop(0)
        changed = True
        while changed:
            changed = False
            for i, seg in enumerate(remaining):
                # Try to connect: current end -> seg start
                if _coords_close(current[-1], seg[0]):
                    current.extend(seg[1:])
                    remaining.pop(i)
                    changed = True
                    break
                # current end -> seg end (reverse seg)
                if _coords_close(current[-1], seg[-1]):
                    current.extend(reversed(seg[:-1]))
                    remaining.pop(i)
                    changed = True
                    break
                # seg end -> current start
                if _coords_close(seg[-1], current[0]):
                    current = seg + current[1:]
                    remaining.pop(i)
                    changed = True
                    break
                # seg start -> current start (reverse seg)
                if _coords_close(seg[0], current[0]):
                    current = list(reversed(seg)) + current[1:]
                    remaining.pop(i)
                    changed = True
                    break

        # Close the ring if not already
        if not _coords_close(current[0], current[-1]):
            current.append(current[0])
        rings.append(current)

    return rings


def _coords_close(a: list[float], b: list[float], tol: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _sanitize_osm_token(value) -> str:
    """Strip a tag key/value to characters safe inside an Overpass query string.

    OSM keys/values are alphanumeric + underscore + colon + dash. Anything else
    (quotes, brackets, semicolons) would let a model break out of the query.
    """
    if not isinstance(value, str):
        value = str(value)
    return "".join(c for c in value if c.isalnum() or c in "_:-")


class OSMServer:
    description = "OpenStreetMap Overpass API for querying real-world features"
    tool_names = {"osm_search", "osm_boundary", "osm_reverse_geocode", "osm_route_overview"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="osm_search",
                description=(
                    "Search OpenStreetMap for features near a location. "
                    "Returns GeoJSON displayed on the map automatically. "
                    "Use for amenities (hospitals, schools, parks), "
                    "infrastructure (bus_stop, railway, highway), buildings, land use, shops.\n\n"
                    "feature_value accepts THREE forms:\n"
                    "  • Single value, e.g. 'hospital' → exact match ['amenity'='hospital'].\n"
                    "  • '*' or empty string → ANY value of that key. Use this for 'all shops' "
                    "(feature_type='shop', feature_value='*') or 'all amenities'.\n"
                    "  • Pipe-separated list, e.g. 'convenience|supermarket|mall|department_store' "
                    "→ matches any of those values in a single call. Prefer this over multiple calls."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "feature_type": {
                            "type": "string",
                            "description": "OSM tag key: amenity, building, highway, leisure, natural, shop, tourism, landuse, railway, waterway, public_transport, place",
                        },
                        "feature_value": {
                            "type": "string",
                            "description": "OSM tag value. Single value ('hospital'), '*' for any value of the key, or pipe-separated list ('convenience|supermarket|mall').",
                        },
                        "lat": {"type": "number", "description": "Center latitude"},
                        "lng": {"type": "number", "description": "Center longitude"},
                        "radius_meters": {"type": "number", "description": "Search radius in meters (default 1000, max 10000)"},
                    },
                    "required": ["feature_type", "lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="osm_boundary",
                description=(
                    "Fetch a boundary polygon from OpenStreetMap. Returns GeoJSON displayed on the map automatically.\n\n"
                    "TWO MODES — pick one:\n"
                    "1) ADMINISTRATIVE boundary (country/state/district/city). Pass `name` and "
                    "`admin_level` (2=country, 4=state/UT, 5=district, 6=sub-district, 8=city/town).\n"
                    "2) SUB-CITY feature (Indian sector, neighborhood, suburb, colony, ward). Pass "
                    "`name`, `place_type` ('suburb' | 'neighbourhood' | 'quarter' | 'village'), AND "
                    "`parent` (the containing city, e.g. 'Chandigarh'). Do NOT set admin_level here — "
                    "sectors/neighborhoods are NOT administrative boundaries in OSM.\n\n"
                    "ALWAYS pass `country_code` (e.g. 'IN' for India) — it dramatically improves accuracy.\n\n"
                    "RETRY STRATEGY — keep trying if a call returns empty or errors. Do not give up after one attempt:\n"
                    "  • Chandigarh sectors are often split into halves in OSM. If 'Sector 30' returns nothing, "
                    "retry with 'Sector 30 A' and 'Sector 30 B' separately.\n"
                    "  • Try name variants: 'Sector-30', 'Sector 30, Chandigarh', regional spellings.\n"
                    "  • Cycle through place_type values: 'suburb' → 'neighbourhood' → 'quarter' → 'residential'.\n"
                    "  • As a last resort, call osm_search with feature_type='place', feature_value='suburb', "
                    "lat/lng at the city center, radius_meters=5000 — then read sector names off the returned features.\n"
                    "  • If still empty, you can use osm_reverse_geocode at a known coordinate inside the sector "
                    "to confirm the OSM name, then re-query osm_boundary with that exact name."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Place name, e.g. 'Chandigarh', 'Sector 30', 'Sector 30 A', 'Punjab'",
                        },
                        "admin_level": {
                            "type": "number",
                            "description": "OSM admin level for administrative boundaries: 2=country, 4=state/UT, 5=district, 6=sub-district, 8=city/town. OMIT this when using place_type.",
                        },
                        "place_type": {
                            "type": "string",
                            "description": "OSM `place` tag value for sub-city features. Use 'suburb' or 'neighbourhood' for Indian sectors/colonies, 'quarter' for urban districts, 'village'/'hamlet' for rural. When set, admin_level is ignored.",
                        },
                        "parent": {
                            "type": "string",
                            "description": "Containing city/region for disambiguation, e.g. 'Chandigarh'. Strongly recommended for sub-city queries.",
                        },
                        "country_code": {
                            "type": "string",
                            "description": "ISO 3166-1 alpha-2 country code, e.g. 'IN', 'US', 'GB'. Always pass this.",
                        },
                    },
                    "required": ["name"],
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
        elif tool_name == "osm_boundary":
            return await self._fetch_boundary(args)
        elif tool_name == "osm_reverse_geocode":
            return await self._reverse_geocode(args)
        elif tool_name == "osm_route_overview":
            return await self._route_overview(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _osm_search(self, args: dict) -> dict:
        feature_type = _sanitize_osm_token(args.get("feature_type", "amenity")) or "amenity"
        raw_value = args.get("feature_value", "")
        lat = args.get("lat", 0)
        lng = args.get("lng", 0)
        radius = min(int(args.get("radius_meters", 1000)), 10000)

        # Build the tag filter:
        #   '' or '*'  → existence check ["key"]
        #   list / 'a|b|c' → regex match ["key"~"a|b|c"]
        #   single token → exact match ["key"="value"]
        if isinstance(raw_value, list):
            values = [_sanitize_osm_token(v) for v in raw_value if v]
            values = [v for v in values if v]
        elif isinstance(raw_value, str):
            stripped = raw_value.strip()
            if stripped in ("", "*"):
                values = []
            elif "|" in stripped:
                values = [_sanitize_osm_token(v) for v in stripped.split("|") if v.strip()]
                values = [v for v in values if v]
            else:
                token = _sanitize_osm_token(stripped)
                values = [token] if token else []
        else:
            values = []

        if not values:
            tag_filter = f'["{feature_type}"]'
        elif len(values) == 1:
            tag_filter = f'["{feature_type}"="{values[0]}"]'
        else:
            tag_filter = f'["{feature_type}"~"^({"|".join(values)})$"]'

        overpass_query = f"""
[out:json][timeout:25];
(
  node{tag_filter}(around:{radius},{lat},{lng});
  way{tag_filter}(around:{radius},{lat},{lng});
  relation{tag_filter}(around:{radius},{lat},{lng});
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

    async def _fetch_boundary(self, args: dict) -> dict:
        name = args.get("name", "")
        place_type = (args.get("place_type") or "").strip()
        parent = (args.get("parent") or "").strip()
        country_code = (args.get("country_code") or "").strip()

        if not name:
            return {"error": "Place name is required"}

        try:
            geojson_feature: dict | None = None

            if place_type:
                # Sub-city features (sectors, neighborhoods). Nominatim with a
                # parent + country handles these far better than raw Overpass.
                geojson_feature = await self._nominatim_boundary(
                    name=name, country_code=country_code,
                    parent=parent, place_type=place_type,
                )
                if not geojson_feature:
                    overpass_query = (
                        f'[out:json][timeout:30];'
                        f'(way["name"~"{name}",i]["place"~"{place_type}"];'
                        f' relation["name"~"{name}",i]["place"~"{place_type}"];);'
                        f'out geom;'
                    )
                    geojson_feature = await self._overpass_boundary(overpass_query)

                if not geojson_feature:
                    return {"error": (
                        f"No boundary found for '{name}'"
                        + (f" in '{parent}'" if parent else "")
                        + f" as place_type='{place_type}'. "
                        f"Retry with a name variant ('{name} A', '{name} B'), "
                        f"a different place_type ('suburb','neighbourhood','quarter','residential'), "
                        f"or call osm_search(feature_type='place', feature_value='suburb') near the city center."
                    )}
            else:
                admin_level = str(int(args.get("admin_level", 4)))
                overpass_query = (
                    f'[out:json][timeout:30];'
                    f'relation["name"~"^{name}$",i]["admin_level"="{admin_level}"]'
                    f'["boundary"="administrative"];'
                    f'out geom;'
                )

                if country_code:
                    geojson_feature = await self._nominatim_boundary(
                        name=name, country_code=country_code, parent=parent,
                    )
                    if not geojson_feature:
                        geojson_feature = await self._overpass_boundary(overpass_query)
                else:
                    geojson_feature = await self._overpass_boundary(overpass_query)
                    if not geojson_feature:
                        geojson_feature = await self._nominatim_boundary(
                            name=name, country_code="", parent=parent,
                        )

                if not geojson_feature:
                    return {"error": (
                        f"No administrative boundary for '{name}' at admin_level {admin_level}. "
                        f"If this is a sector/neighborhood, retry with place_type='suburb' "
                        f"and parent='<city>'. Otherwise try a different admin_level or pass country_code."
                    )}

            geojson = {"type": "FeatureCollection", "features": [geojson_feature]}
            return {
                "geojson": geojson,
                "name": geojson_feature.get("properties", {}).get("name", name),
            }
        except Exception as e:
            return {"error": str(e)}

    async def _overpass_boundary(self, query: str) -> dict | None:
        """Run an Overpass query and convert the first relation/way result to a GeoJSON Feature."""
        async with httpx.AsyncClient(timeout=35) as http:
            resp = await http.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
            )
            if resp.status_code != 200:
                return None
            try:
                data = resp.json()
            except Exception:
                return None

        elements = data.get("elements", [])
        for el in elements:
            if el.get("type") == "relation":
                feature = self._relation_to_geojson(el)
                if feature:
                    return feature
        for el in elements:
            if el.get("type") == "way":
                feature = self._way_to_geojson(el)
                if feature:
                    return feature
        return None

    async def _nominatim_boundary(
        self,
        name: str,
        country_code: str,
        parent: str = "",
        place_type: str = "",
    ) -> dict | None:
        """Search Nominatim and return a GeoJSON polygon (uses polygon_geojson=1)."""
        query_str = f"{name}, {parent}" if parent else name
        params: dict = {
            "q": query_str,
            "format": "json",
            "limit": 10,
            "addressdetails": 1,
            "polygon_geojson": 1,
        }
        if country_code:
            params["countrycodes"] = country_code.lower()

        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
                headers={"User-Agent": "CursorUrbanPlanners/1.0"},
            )
            try:
                results = resp.json()
            except Exception:
                return None

        if not results:
            return None

        # Pick best match. If place_type is set, prefer that; otherwise prefer
        # relations (admin boundaries), then ways.
        chosen = None
        if place_type:
            for r in results:
                if r.get("type") == place_type:
                    chosen = r
                    break
            if not chosen:
                for r in results:
                    if r.get("class") == "place":
                        chosen = r
                        break
        if not chosen:
            for r in results:
                if r.get("osm_type") == "relation":
                    chosen = r
                    break
        if not chosen:
            for r in results:
                if r.get("osm_type") == "way":
                    chosen = r
                    break
        if not chosen:
            chosen = results[0]

        polygon = chosen.get("geojson")
        if polygon and polygon.get("type") in ("Polygon", "MultiPolygon"):
            display = chosen.get("display_name", name)
            return {
                "type": "Feature",
                "geometry": polygon,
                "properties": {
                    "name": display.split(",")[0].strip() if display else name,
                    "osm_id": chosen.get("osm_id"),
                    "osm_type": chosen.get("osm_type"),
                    "class": chosen.get("class"),
                    "type": chosen.get("type"),
                },
            }

        # Polygon not directly returned — fall back to Overpass by id
        osm_id = chosen.get("osm_id")
        osm_type = chosen.get("osm_type")
        if not osm_id:
            return None
        if osm_type == "way":
            query = f'[out:json][timeout:30];way({osm_id});out geom;'
        else:
            query = f'[out:json][timeout:30];relation({osm_id});out geom;'
        return await self._overpass_boundary(query)

    @staticmethod
    def _way_to_geojson(element: dict) -> dict | None:
        """Convert an Overpass way element (with geometry) to a Polygon Feature."""
        geom = element.get("geometry") or []
        coords = [[pt["lon"], pt["lat"]] for pt in geom if "lon" in pt and "lat" in pt]
        if len(coords) < 3:
            return None
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        tags = element.get("tags", {})
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "name": tags.get("name", ""),
                "osm_id": element.get("id"),
                "osm_type": "way",
                "place": tags.get("place", ""),
            },
        }

    @staticmethod
    def _relation_to_geojson(element: dict) -> dict | None:
        """Convert an Overpass relation element (with geometry) to a GeoJSON Feature."""
        members = element.get("members", [])
        tags = element.get("tags", {})

        outer_rings: list[list[list[float]]] = []
        inner_rings: list[list[list[float]]] = []

        for member in members:
            role = member.get("role", "")
            geom = member.get("geometry")
            if not geom or member.get("type") != "way":
                continue
            coords = [[pt["lon"], pt["lat"]] for pt in geom if "lon" in pt and "lat" in pt]
            if len(coords) < 3:
                continue
            if role == "inner":
                inner_rings.append(coords)
            else:
                outer_rings.append(coords)

        if not outer_rings:
            return None

        # Merge outer way segments into closed rings
        merged_outers = _merge_ways(outer_rings)
        merged_inners = _merge_ways(inner_rings) if inner_rings else []

        if not merged_outers:
            return None

        if len(merged_outers) == 1:
            rings = [merged_outers[0]] + merged_inners
            geometry = {"type": "Polygon", "coordinates": rings}
        else:
            polygons = [[ring] for ring in merged_outers]
            geometry = {"type": "MultiPolygon", "coordinates": polygons}

        return {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "name": tags.get("name", ""),
                "admin_level": tags.get("admin_level", ""),
                "osm_id": element.get("id"),
                **{k: v for k, v in tags.items() if k in (
                    "name:en", "boundary", "wikidata", "wikipedia", "population",
                )},
            },
        }

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
