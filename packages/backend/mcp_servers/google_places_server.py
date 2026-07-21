"""Google Maps Platform — Places API v1 + Area Insights.

Four tools:
  - ``places_autocomplete``  — typeahead / structured place suggestions.
  - ``place_details``        — Essentials SKU fields for a known place_id.
  - ``nearby_places``        — Nearby Search (POIs by type, with brand names).
  - ``places_density``       — Aggregate place counts inside a circle.

``nearby_places`` returns a GeoJSON FeatureCollection with the same
top-level shape as ``overture_places_search`` (``geojson`` + ``count``)
so the auto-display branch in ``routers/chat.py`` can route either tool
through the same `add_geojson` action.

FieldMasks are deliberately minimal — Place Details extras (reviews,
photos, opening hours) escalate the SKU above Essentials and burn quota,
so we keep the default mask scoped to free-tier fields.
"""

from __future__ import annotations

import math

from shapely.geometry import Point, Polygon, shape

from llm.base import ToolDeclaration
from tools import cache
from tools.google import GoogleUnavailable, call_v1


_PLACES_BASE = "https://places.googleapis.com/v1"
_INSIGHTS_URL = "https://areainsights.googleapis.com/v1:computeInsights"

_NEARBY_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.types,places.primaryType,places.primaryTypeDisplayName,"
    "places.shortFormattedAddress,places.businessStatus"
)
# Essentials-only mask — adding rating, openingHours, reviews escalates SKU.
_DETAILS_FIELD_MASK_DEFAULT = (
    "id,displayName,formattedAddress,location,types,primaryType,"
    "primaryTypeDisplayName,addressComponents,plusCode"
)
_AUTOCOMPLETE_FIELD_MASK = (
    "suggestions.placePrediction.placeId,"
    "suggestions.placePrediction.structuredFormat,"
    "suggestions.placePrediction.types"
)

_NEARBY_MAX_RESULTS = 20
_NEARBY_RADIUS_MAX = 50_000  # Google hard cap.


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


class GooglePlacesServer:
    description = "Google Places v1: autocomplete, details, nearby search, density (Area Insights)"
    tool_names = {
        "places_autocomplete", "place_details", "nearby_places",
        "nearby_places_in_polygon", "places_density",
    }

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="places_autocomplete",
                description=(
                    "Get place-name suggestions for a partial query — Google Places Autocomplete. "
                    "Use this to disambiguate a user's typed place name BEFORE running searches. "
                    "Returns up to 5 suggestions with place_id, primary text (e.g. 'Sector 17'), "
                    "secondary text (e.g. 'Chandigarh, India'), and types. Pair with `place_details` "
                    "to resolve the chosen suggestion to coordinates."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Partial place name"},
                        "lat": {"type": "number", "description": "Optional bias center latitude"},
                        "lng": {"type": "number", "description": "Optional bias center longitude"},
                        "radius_meters": {
                            "type": "number",
                            "description": "Optional bias radius around (lat,lng)",
                        },
                        "language": {"type": "string", "description": "BCP-47 language code (default 'en')"},
                        "region": {"type": "string", "description": "ISO 3166-1 region bias, e.g. 'in'"},
                    },
                    "required": ["query"],
                },
            ),
            ToolDeclaration(
                name="place_details",
                description=(
                    "Resolve a Google place_id to its full Essentials-tier details: display name, "
                    "formatted address, lat/lng, types, address components. Free-tier fields only — "
                    "reviews/photos/opening hours are intentionally omitted to avoid SKU escalation."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "place_id": {"type": "string"},
                    },
                    "required": ["place_id"],
                },
            ),
            ToolDeclaration(
                name="nearby_places",
                description=(
                    "Find COMMERCIAL POIs near a location — Google Nearby Search Pro. PREFER THIS "
                    "over `osm_search` and `overture_places_search` for restaurants, hotels, retail, "
                    "services, hospitals, schools — Google has the freshest brand and category data. "
                    "Results are auto-displayed on the map. `included_types` accepts Google place "
                    "types (e.g. 'restaurant', 'hospital', 'school', 'shopping_mall'); see "
                    "https://developers.google.com/maps/documentation/places/web-service/place-types "
                    "for the full table."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "radius_meters": {
                            "type": "number",
                            "description": f"Search radius (default 1000, max {_NEARBY_RADIUS_MAX}).",
                        },
                        "included_types": {
                            "type": "array",
                            "description": "Google place type strings to include",
                            "items": {"type": "string"},
                        },
                        "max_results": {
                            "type": "number",
                            "description": f"Max results (default 10, hard cap {_NEARBY_MAX_RESULTS}).",
                        },
                        "rank_by": {
                            "type": "string",
                            "description": "POPULARITY (default) or DISTANCE",
                            "enum": ["POPULARITY", "DISTANCE"],
                        },
                    },
                    "required": ["lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="nearby_places_in_polygon",
                description=(
                    "Find COMMERCIAL POIs INSIDE a polygon — Google Nearby Search Pro, clipped. "
                    "Use this when the user asks for POIs within a drawn region, sector boundary, "
                    "or any non-circular area. Internally: computes the polygon centroid + a "
                    "bounding circle (capped at 50km), runs `nearby_places`, then filters results "
                    "to points actually inside the polygon. Same shape as `nearby_places` "
                    "(`{geojson, count}`) and auto-displayed on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "polygon": {
                            "type": "array",
                            "description": "Polygon ring as [[lng,lat], ...]",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "geojson": {
                            "type": "object",
                            "description": "Alternative: full GeoJSON Feature/Polygon/MultiPolygon",
                        },
                        "included_types": {
                            "type": "array",
                            "description": "Google place type strings (e.g. 'school', 'restaurant')",
                            "items": {"type": "string"},
                        },
                        "max_results": {
                            "type": "number",
                            "description": f"Max results from upstream (hard cap {_NEARBY_MAX_RESULTS}).",
                        },
                        "rank_by": {
                            "type": "string",
                            "enum": ["POPULARITY", "DISTANCE"],
                        },
                    },
                },
            ),
            ToolDeclaration(
                name="places_density",
                description=(
                    "Count places of given types inside a circle — Google Area Insights "
                    "(`computeInsights` with INSIGHT_COUNT). Useful for density / coverage analysis "
                    "without listing every place. Pair with `gis_buffer` and `add_geojson` to "
                    "visualize the search area."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "radius_meters": {
                            "type": "number",
                            "description": f"Radius (default 1000, max {_NEARBY_RADIUS_MAX}).",
                        },
                        "included_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "At least one Google place type",
                        },
                    },
                    "required": ["lat", "lng", "included_types"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "places_autocomplete":
            return await self._autocomplete(args)
        if tool_name == "place_details":
            return await self._details(args)
        if tool_name == "nearby_places":
            return await self._nearby(args)
        if tool_name == "nearby_places_in_polygon":
            return await self._nearby_in_polygon(args)
        if tool_name == "places_density":
            return await self._density(args)
        return {"error": f"Unknown tool: {tool_name}"}

    # ── Autocomplete ───────────────────────────────────────────────────────

    async def _autocomplete(self, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return {"error": "query is required", "code": "bad_request"}

        body: dict = {"input": query}
        lat = args.get("lat")
        lng = args.get("lng")
        radius = args.get("radius_meters")
        if lat is not None and lng is not None:
            try:
                circle = {
                    "center": {"latitude": float(lat), "longitude": float(lng)},
                    "radius": float(radius) if radius else 50_000.0,
                }
                body["locationBias"] = {"circle": circle}
            except (TypeError, ValueError):
                pass
        if args.get("language"):
            body["languageCode"] = str(args["language"])
        if args.get("region"):
            body["regionCode"] = str(args["region"])

        cache_key = {
            "q": query.lower(),
            "lat": round(float(lat), 4) if lat is not None else None,
            "lng": round(float(lng), 4) if lng is not None else None,
            "radius": int(radius) if radius else None,
            "lang": body.get("languageCode"),
            "region": body.get("regionCode"),
        }

        async def _fetch() -> dict:
            payload = await call_v1(
                f"{_PLACES_BASE}/places:autocomplete",
                namespace="google_places",
                method="POST",
                json_body=body,
                field_mask=_AUTOCOMPLETE_FIELD_MASK,
            )
            suggestions = []
            for sug in payload.get("suggestions") or []:
                pred = sug.get("placePrediction") or {}
                struct = pred.get("structuredFormat") or {}
                primary = (struct.get("mainText") or {}).get("text", "")
                secondary = (struct.get("secondaryText") or {}).get("text", "")
                suggestions.append({
                    "place_id": pred.get("placeId"),
                    "primary_text": primary,
                    "secondary_text": secondary,
                    "types": pred.get("types") or [],
                })
            return {"suggestions": suggestions, "count": len(suggestions)}

        try:
            return await cache.get_or_fetch(
                namespace="google_places_autocomplete",
                key=cache_key,
                ttl_seconds=86_400 * 7,
                fetch_fn=_fetch,
            )
        except GoogleUnavailable as e:
            return {"error": str(e), "code": "upstream_unavailable"}

    # ── Place Details ──────────────────────────────────────────────────────

    async def _details(self, args: dict) -> dict:
        place_id = (args.get("place_id") or "").strip()
        if not place_id:
            return {"error": "place_id is required", "code": "bad_request"}

        cache_key = {"place_id": place_id}

        async def _fetch() -> dict:
            payload = await call_v1(
                f"{_PLACES_BASE}/places/{place_id}",
                namespace="google_places",
                method="GET",
                field_mask=_DETAILS_FIELD_MASK_DEFAULT,
            )
            loc = payload.get("location") or {}
            return {
                "place_id": payload.get("id") or place_id,
                "display_name": (payload.get("displayName") or {}).get("text", ""),
                "formatted_address": payload.get("formattedAddress", ""),
                "lat": loc.get("latitude"),
                "lng": loc.get("longitude"),
                "types": payload.get("types") or [],
                "primary_type": payload.get("primaryType"),
                "primary_type_display": (payload.get("primaryTypeDisplayName") or {}).get("text", ""),
                "address_components": payload.get("addressComponents") or [],
                "plus_code": payload.get("plusCode") or {},
            }

        try:
            return await cache.get_or_fetch(
                namespace="google_places_details",
                key=cache_key,
                ttl_seconds=86_400 * 7,
                fetch_fn=_fetch,
            )
        except GoogleUnavailable as e:
            return {"error": str(e), "code": "upstream_unavailable"}

    # ── Nearby Search ──────────────────────────────────────────────────────

    async def _nearby(self, args: dict) -> dict:
        try:
            lat = float(args["lat"])
            lng = float(args["lng"])
        except (KeyError, TypeError, ValueError):
            return {"error": "lat and lng are required", "code": "bad_request"}

        radius = min(float(args.get("radius_meters", 1000)), _NEARBY_RADIUS_MAX)
        max_results = min(int(args.get("max_results", 10)), _NEARBY_MAX_RESULTS)
        included_types = args.get("included_types") or []
        if isinstance(included_types, str):
            included_types = [included_types]
        rank_by = (args.get("rank_by") or "POPULARITY").upper()
        if rank_by not in {"POPULARITY", "DISTANCE"}:
            rank_by = "POPULARITY"

        body: dict = {
            "maxResultCount": max_results,
            "rankPreference": rank_by,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius,
                },
            },
        }
        if included_types:
            body["includedTypes"] = list(included_types)

        cache_key = {
            "lat": round(lat, 5),
            "lng": round(lng, 5),
            "radius": int(radius),
            "types": sorted(included_types),
            "max_results": max_results,
            "rank_by": rank_by,
        }

        async def _fetch() -> dict:
            payload = await call_v1(
                f"{_PLACES_BASE}/places:searchNearby",
                namespace="google_places",
                method="POST",
                json_body=body,
                field_mask=_NEARBY_FIELD_MASK,
            )
            features = []
            for p in payload.get("places") or []:
                loc = p.get("location") or {}
                lat_p = loc.get("latitude")
                lng_p = loc.get("longitude")
                if lat_p is None or lng_p is None:
                    continue
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng_p, lat_p]},
                    "properties": {
                        "id": p.get("id"),
                        "name": (p.get("displayName") or {}).get("text", ""),
                        "address": p.get("shortFormattedAddress") or p.get("formattedAddress", ""),
                        "primary_type": p.get("primaryType"),
                        "primary_type_display": (p.get("primaryTypeDisplayName") or {}).get("text", ""),
                        "types": p.get("types") or [],
                        "business_status": p.get("businessStatus"),
                        "source": "google_places",
                    },
                })
            return {
                "geojson": {"type": "FeatureCollection", "features": features},
                "count": len(features),
                "included_types": included_types,
            }

        try:
            return await cache.get_or_fetch(
                namespace="google_places_nearby",
                key=cache_key,
                ttl_seconds=86_400,
                fetch_fn=_fetch,
            )
        except GoogleUnavailable as e:
            return {"error": str(e), "code": "upstream_unavailable"}

    # ── Nearby in polygon ──────────────────────────────────────────────────

    async def _nearby_in_polygon(self, args: dict) -> dict:
        """Polygon-clipped nearby search.

        Recipe: centroid → bounding circle (capped at Google's 50km hard limit)
        → `_nearby` → filter to points inside the polygon. The bounding-circle
        cap means results in distant corners of polygons larger than ~100km
        wide may be missed; flagged via `truncated_search` in the response so
        the LLM can warn the user.
        """
        polygon_input = args.get("polygon")
        geojson_input = args.get("geojson")

        try:
            if geojson_input:
                geom_dict = (
                    geojson_input.get("geometry", geojson_input)
                    if isinstance(geojson_input, dict) else geojson_input
                )
                if isinstance(geom_dict, dict) and geom_dict.get("type") == "FeatureCollection":
                    feats = geom_dict.get("features") or []
                    if not feats:
                        return {"error": "Empty FeatureCollection", "code": "bad_request"}
                    geom_dict = feats[0].get("geometry", {})
                poly_geom = shape(geom_dict)
            elif polygon_input:
                if len(polygon_input) < 3:
                    return {"error": "Polygon needs at least 3 vertices", "code": "bad_request"}
                poly_geom = Polygon([(c[0], c[1]) for c in polygon_input])
            else:
                return {"error": "Provide 'polygon' or 'geojson'", "code": "bad_request"}
        except Exception as e:
            return {"error": f"Invalid polygon: {e}", "code": "bad_request"}

        if poly_geom.is_empty:
            return {"error": "Empty polygon", "code": "bad_request"}

        centroid = poly_geom.centroid
        c_lat, c_lng = centroid.y, centroid.x

        # Bounding-circle radius: max haversine distance from centroid to any
        # exterior vertex. Adequate for the typical sector/neighborhood case.
        coords: list[tuple[float, float]] = []
        if poly_geom.geom_type == "Polygon":
            coords = list(poly_geom.exterior.coords)
        elif poly_geom.geom_type == "MultiPolygon":
            for p in poly_geom.geoms:
                coords.extend(list(p.exterior.coords))
        if not coords:
            return {"error": "Polygon has no exterior coordinates", "code": "bad_request"}

        max_radius_m = max(_haversine_m(c_lat, c_lng, lat, lng) for lng, lat in coords)
        truncated = max_radius_m > _NEARBY_RADIUS_MAX
        radius_m = min(max_radius_m, float(_NEARBY_RADIUS_MAX))

        nearby_args = {
            "lat": c_lat,
            "lng": c_lng,
            "radius_meters": radius_m,
            "included_types": args.get("included_types") or [],
            "max_results": args.get("max_results", _NEARBY_MAX_RESULTS),
            "rank_by": args.get("rank_by", "POPULARITY"),
        }
        nearby_result = await self._nearby(nearby_args)
        if "error" in nearby_result:
            return nearby_result

        features_in = []
        for feat in (nearby_result.get("geojson") or {}).get("features") or []:
            geom = feat.get("geometry") or {}
            coord = geom.get("coordinates") or []
            if len(coord) < 2:
                continue
            if poly_geom.contains(Point(coord[0], coord[1])):
                features_in.append(feat)

        return {
            "geojson": {"type": "FeatureCollection", "features": features_in},
            "count": len(features_in),
            "included_types": args.get("included_types") or [],
            "search_radius_meters": int(radius_m),
            "centroid": {"lat": round(c_lat, 6), "lng": round(c_lng, 6)},
            "truncated_search": truncated,
            "upstream_count": nearby_result.get("count", 0),
        }

    # ── Density (Area Insights) ────────────────────────────────────────────

    async def _density(self, args: dict) -> dict:
        try:
            lat = float(args["lat"])
            lng = float(args["lng"])
        except (KeyError, TypeError, ValueError):
            return {"error": "lat and lng are required", "code": "bad_request"}

        included_types = args.get("included_types") or []
        if isinstance(included_types, str):
            included_types = [included_types]
        if not included_types:
            return {"error": "included_types must be a non-empty list", "code": "bad_request"}

        radius = min(float(args.get("radius_meters", 1000)), _NEARBY_RADIUS_MAX)

        body = {
            "insights": ["INSIGHT_COUNT"],
            "filter": {
                "locationFilter": {
                    "circle": {
                        "latLng": {"latitude": lat, "longitude": lng},
                        "radius": radius,
                    },
                },
                "typeFilter": {"includedTypes": list(included_types)},
            },
        }

        cache_key = {
            "lat": round(lat, 5),
            "lng": round(lng, 5),
            "radius": int(radius),
            "types": sorted(included_types),
        }

        async def _fetch() -> dict:
            payload = await call_v1(
                _INSIGHTS_URL,
                namespace="google_places",
                method="POST",
                json_body=body,
            )
            count = payload.get("count")
            try:
                count_int = int(count) if count is not None else None
            except (TypeError, ValueError):
                count_int = None
            return {
                "count": count_int,
                "included_types": included_types,
                "radius_meters": int(radius),
                "center": {"lat": lat, "lng": lng},
            }

        try:
            return await cache.get_or_fetch(
                namespace="google_places_density",
                key=cache_key,
                ttl_seconds=86_400,
                fetch_fn=_fetch,
            )
        except GoogleUnavailable as e:
            return {"error": str(e), "code": "upstream_unavailable"}
