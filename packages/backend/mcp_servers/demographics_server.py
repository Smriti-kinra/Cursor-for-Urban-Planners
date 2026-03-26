"""
Demographics — approximate population context near a point using OSM tags + Nominatim.

Not a substitute for official census microdata; useful for planning context.
"""

from __future__ import annotations

import httpx
from llm.base import ToolDeclaration


class DemographicsServer:
    description = "Population and place context from OpenStreetMap around coordinates"
    tool_names = {"get_demographics"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="get_demographics",
                description=(
                    "Estimate population context near a point: finds nearby OSM places with population tags, "
                    "and reverse-geocoded hierarchy. Useful for urban planning scoping."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "radius_meters": {
                            "type": "number",
                            "description": "Search radius for tagged places (default 8000, max 25000)",
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
        r = min(int(args.get("radius_meters", 8000)), 25000)

        headers = {"User-Agent": "CursorUrbanPlanners/1.0"}
        out: dict = {
            "input": {"lat": lat, "lng": lng, "radius_meters": r},
            "places_with_population": [],
            "reverse_geocode_summary": None,
            "notes": (
                "Population figures come from OpenStreetMap tags when present; they may be outdated or missing. "
                "Use official census for statutory work."
            ),
        }

        try:
            async with httpx.AsyncClient(timeout=20) as http:
                rev = await http.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={
                        "lat": lat,
                        "lon": lng,
                        "format": "json",
                        "addressdetails": 1,
                        "zoom": 10,
                    },
                    headers=headers,
                )
                rd = rev.json()
                out["reverse_geocode_summary"] = {
                    "display_name": rd.get("display_name", ""),
                    "type": rd.get("type", ""),
                    "address": rd.get("address", {}),
                }
        except Exception as e:
            out["reverse_geocode_error"] = str(e)

        overpass = (
            f'[out:json][timeout:25];'
            f'('
            f'node["population"](around:{r},{lat},{lng});'
            f'way["population"](around:{r},{lat},{lng});'
            f');'
            f'out center tags 18;'
        )
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                resp = await http.post(
                    "https://overpass-api.de/api/interpreter",
                    data={"data": overpass},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    seen = set()
                    for el in data.get("elements", [])[:25]:
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
                        out["places_with_population"].append({
                            "name": name,
                            "population": pop,
                            "place": tags.get("place", ""),
                            "admin_level": tags.get("admin_level", ""),
                            "lat": plat,
                            "lon": plon,
                        })
        except Exception as e:
            out["overpass_error"] = str(e)

        return out
