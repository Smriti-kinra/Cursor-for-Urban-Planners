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
    description = "Population around coordinates (WorldPop 100m grid, OSM fallback) and population forecasting growth models"
    tool_names = {"get_demographics", "project_population"}

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
            ToolDeclaration(
                name="project_population",
                description=(
                    "Forecast future population growth for a study area. Can automatically retrieve the current baseline "
                    "population at a coordinate, or accept an explicit baseline population value. Supports linear, "
                    "exponential, and logistic models with annual growth rate, target years, and carrying capacity constraints."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "base_population": {
                            "type": "integer",
                            "description": "Baseline population. If not specified, lat and lng must be provided to fetch current gridded population."
                        },
                        "growth_rate": {
                            "type": "number",
                            "description": "Annual population growth rate as a decimal (e.g. 0.025 for 2.5% growth). Default: 0.02"
                        },
                        "target_years": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of future years to calculate projections for (e.g. [2030, 2040, 2050]). Default: [2030, 2035, 2040, 2045, 2050]"
                        },
                        "model_type": {
                            "type": "string",
                            "enum": ["exponential", "linear", "logistic"],
                            "description": "Growth model formulation. Default: exponential"
                        },
                        "carrying_capacity": {
                            "type": "integer",
                            "description": "Upper population ceiling constraint for the logistic model. Required if model_type is 'logistic'."
                        },
                        "lat": {
                            "type": "number",
                            "description": "Latitude to fetch base population (optional if base_population is provided)."
                        },
                        "lng": {
                            "type": "number",
                            "description": "Longitude to fetch base population (optional if base_population is provided)."
                        },
                        "radius_meters": {
                            "type": "number",
                            "description": "Demographic search radius in meters (default 5000)."
                        }
                    },
                    "required": []
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "get_demographics":
            return await self._get_demographics(args)
        if tool_name == "project_population":
            return await self._project_population(args)
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

    async def _project_population(self, args: dict) -> dict:
        import math
        base_pop_arg = args.get("base_population")
        growth_rate = float(args.get("growth_rate", 0.02))
        target_years = args.get("target_years") or [2030, 2035, 2040, 2045, 2050]
        model_type = args.get("model_type", "exponential").strip().lower()
        carrying_capacity = args.get("carrying_capacity")
        lat_arg = args.get("lat")
        lng_arg = args.get("lng")
        radius = int(args.get("radius_meters", 5000))

        # 1. Resolve base population
        base_population = None
        source_summary = ""

        if base_pop_arg is not None:
            try:
                base_population = int(base_pop_arg)
                source_summary = "User-supplied explicit baseline value"
            except (ValueError, TypeError):
                return {"error": "Invalid base_population value. Must be an integer."}

        elif lat_arg is not None and lng_arg is not None:
            # Query WorldPop/OSM demographics at these coordinates
            demog_args = {"lat": float(lat_arg), "lng": float(lng_arg), "radius_meters": radius}
            demog_res = await self._get_demographics(demog_args)
            if demog_res.get("population") is not None:
                base_population = demog_res["population"]
                # Extract a human-readable place name from the reverse geocode summary
                rev = demog_res.get("reverse_geocode_summary") or {}
                addr = rev.get("address", {})
                place_name_raw = (
                    addr.get("city")
                    or addr.get("town")
                    or addr.get("district")
                    or addr.get("county")
                    or addr.get("state")
                    or ""
                )
                source_summary = (
                    f"Geolocated baseline near {place_name_raw} ({lat_arg}, {lng_arg}) "
                    f"using {demog_res['population_source']} source."
                    if place_name_raw
                    else f"Geolocated baseline around coordinates ({lat_arg}, {lng_arg}) using {demog_res['population_source']} source."
                )
            else:
                return {"error": f"Could not determine baseline population at coordinates ({lat_arg}, {lng_arg}). Please specify base_population explicitly."}
        else:
            return {"error": "Either base_population or geocoding lat/lng coordinates must be provided."}

        if base_population <= 0:
            return {"error": f"Base population must be greater than zero. Received: {base_population}"}

        if model_type == "logistic":
            if carrying_capacity is None:
                return {"error": "carrying_capacity limit is required when model_type is set to 'logistic'."}
            try:
                carrying_capacity = int(carrying_capacity)
            except (ValueError, TypeError):
                return {"error": "Invalid carrying_capacity value. Must be an integer."}
            if carrying_capacity <= base_population:
                return {"error": f"Carrying capacity ceiling ({carrying_capacity}) must be greater than the base population ({base_population})."}

        # 2. Run projection
        base_year = 2026  # default planning baseline year
        results = []

        # Sort years to be chronological
        sorted_years = sorted(list(set([int(y) for y in target_years if int(y) > base_year])))
        if not sorted_years:
            return {"error": f"All target years must be greater than the current baseline year {base_year}."}

        for yr in sorted_years:
            dt = yr - base_year
            if model_type == "linear":
                proj = base_population * (1.0 + growth_rate * dt)
            elif model_type == "logistic":
                try:
                    exp_factor = math.exp(growth_rate * dt)
                    numerator = carrying_capacity * base_population * exp_factor
                    denominator = carrying_capacity + base_population * (exp_factor - 1.0)
                    proj = numerator / denominator
                except OverflowError:
                    proj = carrying_capacity
            else:  # exponential (default)
                try:
                    proj = base_population * math.exp(growth_rate * dt)
                except OverflowError:
                    proj = float("inf")

            results.append({
                "year": yr,
                "projected_population": round(proj),
                "growth_increment": round(proj - base_population)
            })

        # 3. Create a Markdown report comparison table
        md = []
        md.append(f"# Population Projection Report")
        md.append(f"**Baseline Year:** {base_year}")
        md.append(f"**Baseline Population:** {base_population:,}")
        md.append(f"**Annual Growth Rate:** {growth_rate * 100:.2f}%")
        md.append(f"**Projection Model Type:** {model_type.upper()}")
        md.append(f"**Source Context:** {source_summary}")
        if model_type == "logistic":
            md.append(f"**Carrying Capacity Limit:** {carrying_capacity:,}")
        md.append("")
        md.append("| Target Year | Elapsed Years | Projected Population | Total Growth |")
        md.append("| :--- | :--- | :--- | :--- |")
        for r in results:
            dt = r["year"] - base_year
            md.append(f"| {r['year']} | +{dt} | {r['projected_population']:,} | +{r['growth_increment']:,} |")
        md.append("")

        # Calculate land density requirements (150 people per hectare)
        final_proj = results[-1]["projected_population"]
        total_increment = final_proj - base_population
        required_ha = round(total_increment / 150.0, 1)

        md.append("## Planning Implications & Space Demands")
        md.append(f"Based on a standard density benchmark of 150 persons/hectare, supporting the projected increase of **{total_increment:,}** additional residents by the year **{results[-1]['year']}** will require approximately:")
        md.append(f"* **{required_ha:,} hectares** of newly zoned residential land, OR")
        md.append(f"* A proportional increase in Floor Area Ratio (FAR) within existing built-up sectors to accommodate the influx without expanding the municipal boundary.")

        markdown_report = "\n".join(md)

        # Extract place name for the calling side-effect (chat.py artifact title)
        place_name_for_title = ""
        if source_summary:
            # Pattern: "Geolocated baseline near <CITY> ("
            import re
            m = re.search(r"near ([^(]+)\(", source_summary)
            if m:
                place_name_for_title = m.group(1).strip().rstrip(",")

        return {
            "status": "success",
            "baseline": {
                "year": base_year,
                "population": base_population,
                "source": source_summary
            },
            "growth_rate": growth_rate,
            "model_type": model_type,
            "projections": results,
            "land_demand_hectares": required_ha,
            "place_name": place_name_for_title,
            "report": markdown_report
        }


def _to_int(value) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        return None
