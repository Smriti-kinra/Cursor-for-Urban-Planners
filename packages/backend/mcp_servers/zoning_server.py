"""
Zoning analysis MCP tools — summarize drawn / loaded zone polygons by zone_code.
"""

from __future__ import annotations

import asyncio

from llm.base import ToolDeclaration
from tools.geo import geodesic_area_m2

try:
    from shapely.geometry import shape
    from shapely.ops import unary_union
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False
    shape = unary_union = None


class ZoningServer:
    description = "Zoning: analyze zone-tagged GeoJSON for area breakdown and overlaps"
    tool_names = {"analyze_zones", "detect_zone_overlaps"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="analyze_zones",
                description=(
                    "Given a GeoJSON FeatureCollection where features have properties.zone_code (and optional zone_label), "
                    "compute total area in m², hectares, and percentage per zone_code."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "GeoJSON FeatureCollection of zone polygons",
                        },
                    },
                    "required": ["geojson"],
                },
            ),
            ToolDeclaration(
                name="detect_zone_overlaps",
                description=(
                    "Check pairs of zone polygons for geometric overlap. "
                    "Returns list of overlapping feature index pairs and approximate overlap area."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {"type": "object", "description": "GeoJSON FeatureCollection"},
                    },
                    "required": ["geojson"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "analyze_zones":
            return await asyncio.to_thread(self._analyze_zones, args)
        if tool_name == "detect_zone_overlaps":
            return await asyncio.to_thread(self._detect_overlaps, args)
        return {"error": f"Unknown tool: {tool_name}"}

    def _analyze_zones(self, args: dict) -> dict:
        fc = args.get("geojson") or {}
        feats = fc.get("features", []) if isinstance(fc, dict) else []
        if not feats:
            return {"error": "No features in geojson"}

        by_code: dict[str, float] = {}
        by_label: dict[str, str] = {}

        for f in feats:
            geom = f.get("geometry")
            if not geom:
                continue
            code = str(f.get("properties", {}).get("zone_code") or "unspecified")
            label = f.get("properties", {}).get("zone_label") or code
            by_label[code] = str(label)
            try:
                a = geodesic_area_m2(geom)
            except Exception:
                continue
            by_code[code] = by_code.get(code, 0) + a

        total = sum(by_code.values())
        if total <= 0:
            return {"error": "Could not compute areas"}

        breakdown = []
        for code, m2 in sorted(by_code.items(), key=lambda x: -x[1]):
            breakdown.append({
                "zone_code": code,
                "zone_label": by_label.get(code, code),
                "area_m2": round(m2, 1),
                "area_hectares": round(m2 / 10000, 4),
                "percent_of_total": round(100.0 * m2 / total, 2),
            })

        return {
            "total_area_m2": round(total, 1),
            "total_area_hectares": round(total / 10000, 4),
            "zones": breakdown,
        }

    def _detect_overlaps(self, args: dict) -> dict:
        fc = args.get("geojson") or {}
        feats = fc.get("features", []) if isinstance(fc, dict) else []
        if not HAS_SHAPELY or len(feats) < 2:
            return {"overlaps": [], "note": "Need at least 2 features and shapely for overlap detection"}

        assert shape is not None and unary_union is not None
        polys = []
        for i, f in enumerate(feats):
            try:
                g = shape(f.get("geometry", {}))
                if g.geom_type == "Polygon":
                    polys.append((i, g))
                elif g.geom_type == "MultiPolygon":
                    merged = unary_union(list(g.geoms))
                    polys.append((i, merged))
            except Exception:
                continue

        overlaps = []
        for a in range(len(polys)):
            for b in range(a + 1, len(polys)):
                ia, ga = polys[a]
                ib, gb = polys[b]
                if not ga.intersects(gb):
                    continue
                inter = ga.intersection(gb)
                if inter.is_empty:
                    continue
                try:
                    area_m2 = geodesic_area_m2(inter.__geo_interface__)
                except Exception:
                    area_m2 = 0.0
                overlaps.append({
                    "feature_indices": [ia, ib],
                    "overlaps": True,
                    "overlap_area_m2": round(area_m2, 1),
                })
        return {"overlap_pairs": overlaps, "count": len(overlaps)}
