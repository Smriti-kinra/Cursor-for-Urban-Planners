"""
Demographics — population near a point.

WorldPop (wpgppop, 100m grid, ML-modeled) is the primary source. When it's
unavailable, we fall back to scraping ``population`` tags on nearby OSM places
within the radius — useful for context but inconsistent (some places are
tagged, some aren't).

Both paths return a single shape so the LLM doesn't have to branch.
"""

from __future__ import annotations

from llm.base import ToolDeclaration
from tools import cache, http as http_client, worldpop
from tools.geo import geodesic_buffer


_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


class DemographicsServer:
    description = "Population around coordinates (WorldPop 100m grid, OSM fallback)"
    tool_names = {"get_demographics"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="get_demographics",
                description=(
                    "Estimate population around a point. Primary source: WorldPop's "
                    "wpgppop 100m gridded population (2020). Returns a hard number for "
                    "`population` plus reverse-geocoded place context and any nearby "
                    "OSM-tagged populations. Falls back to OSM tag scrape if WorldPop "
                    "is unavailable."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "radius_meters": {
                            "type": "number",
                            "description": "Search radius (default 8000, max 25000).",
                        },
                    },
                    "required": ["lat", "lng"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "get_demographics":
            return await self._get_demographics(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _get_demographics(self, args: dict) -> dict:
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        radius = min(int(args.get("radius_meters", 8000)), 25000)

        out: dict = {
            "input": {"lat": lat, "lng": lng, "radius_meters": radius},
            "population": None,
            "population_source": None,
            "places_with_population": [],
            "reverse_geocode_summary": None,
            "notes": (
                "WorldPop = ML-modeled 100m grid (2020); OSM = tagged values, "
                "may be outdated or missing. Use official census for statutory work."
            ),
        }

        try:
            point_geom = {"type": "Point", "coordinates": [lng, lat]}
            polygon = geodesic_buffer(point_geom, radius)
            wp_pop = await worldpop.population_in_polygon(polygon)
        except Exception as e:
            wp_pop = None
            out["worldpop_error"] = str(e)

        if wp_pop is not None:
            out["population"] = round(wp_pop)
            out["population_source"] = "worldpop"

        out["reverse_geocode_summary"] = await self._reverse_summary(lat, lng)
        out["places_with_population"] = await self._osm_population_tags(lat, lng, radius)

        if out["population"] is None and out["places_with_population"]:
            tagged = [_to_int(p["population"]) for p in out["places_with_population"]]
            tagged = [t for t in tagged if t is not None]
            if tagged:
                out["population"] = max(tagged)
                out["population_source"] = "osm"

        return out

    @staticmethod
    async def _reverse_summary(lat: float, lng: float) -> dict | None:
        cache_key = {"lat": round(lat, 4), "lng": round(lng, 4), "zoom": 10}

        async def _fetch() -> dict:
            return await http_client.fetch_json(
                "https://nominatim.openstreetmap.org/reverse",
                namespace="nominatim",
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "addressdetails": 1,
                    "zoom": 10,
                },
            )

        try:
            data = await cache.get_or_fetch(
                namespace="nominatim",
                key=cache_key,
                ttl_seconds=86_400 * 7,
                fetch_fn=_fetch,
            )
        except Exception:
            return None
        return {
            "display_name": data.get("display_name", ""),
            "type": data.get("type", ""),
            "address": data.get("address", {}),
        }

    @staticmethod
    async def _osm_population_tags(lat: float, lng: float, radius: int) -> list[dict]:
        query = (
            f"[out:json][timeout:25];"
            f"("
            f'node["population"](around:{radius},{lat},{lng});'
            f'way["population"](around:{radius},{lat},{lng});'
            f");"
            f"out center tags 25;"
        )
        cache_key = {"q": query}

        async def _fetch() -> dict:
            return await http_client.fetch_json(
                _OVERPASS_URL,
                namespace="overpass",
                params={"data": query},
            )

        try:
            data = await cache.get_or_fetch(
                namespace="overpass",
                key=cache_key,
                ttl_seconds=86_400,
                fetch_fn=_fetch,
            )
        except Exception:
            return []

        seen: set = set()
        out: list[dict] = []
        for el in (data or {}).get("elements", [])[:25]:
            tags = el.get("tags", {})
            pop = tags.get("population")
            name = tags.get("name", "")
            if not pop:
                continue
            key = (name, pop)
            if key in seen:
                continue
            seen.add(key)
            center = el.get("center", {})
            plat = center.get("lat") or el.get("lat")
            plon = center.get("lon") or el.get("lon")
            out.append({
                "name": name,
                "population": pop,
                "place": tags.get("place", ""),
                "admin_level": tags.get("admin_level", ""),
                "lat": plat,
                "lon": plon,
            })
        return out


def _to_int(value) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        return None
