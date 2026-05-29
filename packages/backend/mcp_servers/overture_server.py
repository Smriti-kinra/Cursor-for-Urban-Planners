"""Overture Maps MCP Server — Places + Buildings via DuckDB over S3 parquet.

Overture is the open, commercially-permissive successor to OSM POI data:
brand names, richer categories, building heights. Queries hit the public
``s3://overturemaps-us-west-2/`` bucket with no auth.

Two costs to be aware of:
  - **Cold-start latency.** A fresh DuckDB connection plus the first parquet
    read against S3 takes 10–30 seconds. We keep one connection warm at module
    level and cache result sets for 1 day.
  - **Release pinning.** ``OVERTURE_RELEASE`` is a constant and must be bumped
    manually. Schema can drift between releases.

DuckDB is synchronous; queries run in a thread pool via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import math
import threading

from llm.base import ToolDeclaration
from tools import cache


# Bumped manually after smoke-testing the schema. Older releases stay accessible
# at the same URL pattern, so this never breaks at runtime, only stales.
OVERTURE_RELEASE = "2026-05-20.0"
_S3_BASE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"


_RADIUS_METERS_MAX = 5000
_LIMIT_MAX = 200
_CONFIDENCE_THRESHOLD = 0.5


_conn = None
_conn_lock = threading.Lock()


def _get_conn():
    """Return a process-singleton DuckDB connection with spatial + httpfs loaded.

    First call pays the install/load cost (~1s); subsequent calls are free.
    Connection is thread-safe for reads under DuckDB's default settings.
    """
    global _conn
    if _conn is not None:
        return _conn
    with _conn_lock:
        if _conn is not None:
            return _conn
        import duckdb
        c = duckdb.connect(":memory:")
        c.execute("INSTALL spatial; LOAD spatial;")
        c.execute("INSTALL httpfs; LOAD httpfs;")
        c.execute("SET s3_region='us-west-2';")
        # Suppress DuckDB's TTY progress bar — it dumps megabytes of CR-overwrite
        # output that pollutes server logs and any captured tool stdout.
        c.execute("SET enable_progress_bar=false;")
        _conn = c
        return _conn


def _bbox_from_radius(lat: float, lng: float, radius_m: float) -> dict:
    """Approximate bbox around (lat,lng) with `radius_m`. Lat-lng degrees,
    no projection — accurate enough at city scale to gate the parquet scan."""
    dlat = radius_m / 111_320.0
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    dlng = radius_m / (111_320.0 * cos_lat)
    return {
        "west": lng - dlng,
        "east": lng + dlng,
        "south": lat - dlat,
        "north": lat + dlat,
    }


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _places_query(bbox: dict, category: str | None, query: str | None, limit: int) -> tuple[str, list]:
    where = [
        "bbox.xmin >= ? AND bbox.xmin <= ?",
        "bbox.ymin >= ? AND bbox.ymin <= ?",
        "confidence > ?",
    ]
    params: list = [bbox["west"], bbox["east"], bbox["south"], bbox["north"], _CONFIDENCE_THRESHOLD]
    if category:
        where.append("categories.primary = ?")
        params.append(category)
    if query:
        where.append("names.primary ILIKE ?")
        params.append(f"%{query}%")
    sql = f"""
        SELECT
            id,
            names.primary AS name,
            categories.primary AS category,
            bbox.xmin AS lng,
            bbox.ymin AS lat,
            confidence
        FROM read_parquet('{_S3_BASE}/theme=places/type=place/*', hive_partitioning=1)
        WHERE {' AND '.join(where)}
        LIMIT ?
    """
    params.append(limit)
    return sql, params


def _buildings_query(bbox: dict, limit: int) -> tuple[str, list]:
    sql = f"""
        SELECT
            id,
            height,
            num_floors,
            ST_AsGeoJSON(geometry) AS geometry_json,
            ST_X(ST_Centroid(geometry)) AS lng,
            ST_Y(ST_Centroid(geometry)) AS lat
        FROM read_parquet('{_S3_BASE}/theme=buildings/type=building/*', hive_partitioning=1)
        WHERE bbox.xmin >= ? AND bbox.xmax <= ?
          AND bbox.ymin >= ? AND bbox.ymax <= ?
        LIMIT ?
    """
    params = [bbox["west"], bbox["east"], bbox["south"], bbox["north"], limit]
    return sql, params


def _run_query_sync(sql: str, params: list) -> list[dict]:
    conn = _get_conn()
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


class OvertureServer:
    description = "Overture Maps Places + Buildings via DuckDB on S3 parquet"
    tool_names = {"overture_places_search", "overture_buildings_search"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="overture_places_search",
                description=(
                    "Search Overture Maps Places (POIs) near a location. Returns brand-name, "
                    "category-tagged POIs with richer metadata than osm_search. Best for "
                    "COMMERCIAL venues (restaurants, hotels, retail, services). Use osm_search "
                    "for non-commercial OSM-tagged features (water, infrastructure, hand-mapped "
                    "local data). Results are auto-displayed on the map.\n\n"
                    "IMPORTANT: First call for a region takes 1-2 minutes (S3 parquet scan). "
                    "Repeat calls are instant (cached). Tell the user before calling: "
                    "'Searching Overture Maps — this may take up to 2 minutes on the first lookup.'\n\n"
                    "Common Overture categories: restaurant, hotel, school, hospital, park, "
                    "pharmacy, gas_station, bank, supermarket, shopping_mall, cafe, bar."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Center latitude"},
                        "lng": {"type": "number", "description": "Center longitude"},
                        "radius_meters": {
                            "type": "number",
                            "description": f"Search radius in meters (default 1000, max {_RADIUS_METERS_MAX}).",
                        },
                        "category": {
                            "type": "string",
                            "description": "Optional Overture category (e.g. 'restaurant', 'school'). Omit for any.",
                        },
                        "query": {
                            "type": "string",
                            "description": "Optional name substring filter (case-insensitive).",
                        },
                        "limit": {
                            "type": "number",
                            "description": f"Max results (default 50, max {_LIMIT_MAX}).",
                        },
                    },
                    "required": ["lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="overture_buildings_search",
                description=(
                    "Fetch building footprints near a location from Overture Maps. Returns "
                    "polygons with `height` (meters) and `num_floors` where known — useful "
                    "for density and coverage analysis. Results are auto-displayed on the map.\n\n"
                    "IMPORTANT: First call for a region takes 1-2 minutes (S3 parquet scan). "
                    "Repeat calls are instant (cached). Tell the user before calling: "
                    "'Fetching Overture building footprints — this may take up to 2 minutes on the first lookup.'"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"},
                        "radius_meters": {
                            "type": "number",
                            "description": f"Search radius in meters (default 500, max {_RADIUS_METERS_MAX}).",
                        },
                        "limit": {
                            "type": "number",
                            "description": f"Max buildings (default 200, max {_LIMIT_MAX}).",
                        },
                    },
                    "required": ["lat", "lng"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "overture_places_search":
            return await self._places_search(args)
        if tool_name == "overture_buildings_search":
            return await self._buildings_search(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _places_search(self, args: dict) -> dict:
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        radius = min(int(args.get("radius_meters", 1000)), _RADIUS_METERS_MAX)
        category = (args.get("category") or "").strip() or None
        query = (args.get("query") or "").strip() or None
        limit = min(int(args.get("limit", 50)), _LIMIT_MAX)

        bbox = _bbox_from_radius(lat, lng, radius)
        cache_key = {
            "kind": "places",
            "bbox": {k: round(v, 5) for k, v in bbox.items()},
            "category": category,
            "query": query,
            "limit": limit,
        }

        async def _fetch() -> dict:
            sql, params = _places_query(bbox, category, query, limit)
            try:
                rows = await asyncio.to_thread(_run_query_sync, sql, params)
            except Exception as e:
                return {"error": str(e), "code": "upstream_unavailable"}
            return {"rows": rows}

        try:
            payload = await cache.get_or_fetch(
                namespace="overture",
                key=cache_key,
                ttl_seconds=86_400,
                fetch_fn=_fetch,
            )
        except Exception as e:
            return {"error": str(e), "code": "internal"}

        if payload.get("error"):
            return payload

        rows = payload.get("rows") or []
        # Filter by exact circle (bbox is a superset)
        filtered = [
            r for r in rows
            if _haversine_m(lat, lng, r["lat"], r["lng"]) <= radius
        ]

        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
                "properties": {
                    "id": r.get("id"),
                    "name": r.get("name") or "",
                    "category": r.get("category") or "",
                    "confidence": r.get("confidence"),
                    "source": "overture",
                },
            }
            for r in filtered
        ]
        return {
            "geojson": {"type": "FeatureCollection", "features": features},
            "count": len(features),
            "total_count": len(filtered),
            "truncated": len(rows) >= limit,
            "category": category,
            "query": query,
        }

    async def _buildings_search(self, args: dict) -> dict:
        import json as _json
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        radius = min(int(args.get("radius_meters", 500)), _RADIUS_METERS_MAX)
        limit = min(int(args.get("limit", 200)), _LIMIT_MAX)

        bbox = _bbox_from_radius(lat, lng, radius)
        cache_key = {
            "kind": "buildings",
            "bbox": {k: round(v, 5) for k, v in bbox.items()},
            "limit": limit,
        }

        async def _fetch() -> dict:
            sql, params = _buildings_query(bbox, limit)
            try:
                rows = await asyncio.to_thread(_run_query_sync, sql, params)
            except Exception as e:
                return {"error": str(e), "code": "upstream_unavailable"}
            return {"rows": rows}

        try:
            payload = await cache.get_or_fetch(
                namespace="overture",
                key=cache_key,
                ttl_seconds=86_400,
                fetch_fn=_fetch,
            )
        except Exception as e:
            return {"error": str(e), "code": "internal"}

        if payload.get("error"):
            return payload

        rows = payload.get("rows") or []
        filtered = [
            r for r in rows
            if _haversine_m(lat, lng, r["lat"], r["lng"]) <= radius
        ]
        features = []
        for r in filtered:
            try:
                geom = _json.loads(r["geometry_json"])
            except Exception:
                continue
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "id": r.get("id"),
                    "height": r.get("height"),
                    "num_floors": r.get("num_floors"),
                    "source": "overture",
                },
            })
        return {
            "geojson": {"type": "FeatureCollection", "features": features},
            "count": len(features),
            "total_count": len(filtered),
            "truncated": len(rows) >= limit,
        }
