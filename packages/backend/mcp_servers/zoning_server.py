"""
Zoning analysis MCP tools — summarize drawn / loaded zone polygons by zone_code.
"""

from __future__ import annotations

import math
from llm.base import ToolDeclaration

try:
    from shapely.geometry import shape
    from shapely.ops import unary_union
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False


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
            return self._analyze_zones(args)
        if tool_name == "detect_zone_overlaps":
            return self._detect_overlaps(args)
        return {"error": f"Unknown tool: {tool_name}"}

    def _polygon_area_m2(self, coords: list) -> float:
        """Shoelace on projected plane approx for small regions."""
        if len(coords) < 3:
            return 0.0
        R = 6371000.0
        n = len(coords)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            xi = math.radians(coords[i][0]) * R * math.cos(math.radians(coords[i][1]))
            yi = math.radians(coords[i][1]) * R
            xj = math.radians(coords[j][0]) * R * math.cos(math.radians(coords[j][1]))
            yj = math.radians(coords[j][1]) * R
            area += xi * yj - xj * yi
        return abs(area) / 2

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
            gtype = geom.get("type", "")
            coords = geom.get("coordinates", [])

            if gtype == "Polygon" and coords:
                ring = coords[0]
                a = self._polygon_area_m2(ring)
                by_code[code] = by_code.get(code, 0) + a
            elif gtype == "MultiPolygon":
                for poly in coords:
                    if poly:
                        a = self._polygon_area_m2(poly[0])
                        by_code[code] = by_code.get(code, 0) + a
            elif HAS_SHAPELY:
                try:
                    g = shape(geom)
                    if g.is_empty:
                        continue
                    gc = g.convex_hull
                    xs, ys = zip(*list(gc.exterior.coords))
                    ring = [[x, y] for x, y in zip(xs, ys)]
                    a = self._polygon_area_m2(ring)
                    by_code[code] = by_code.get(code, 0) + a * 0.85
                except Exception:
                    continue

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
            "zones": breakdown,
        }

    def _detect_overlaps(self, args: dict) -> dict:
        fc = args.get("geojson") or {}
        feats = fc.get("features", []) if isinstance(fc, dict) else []
        if not HAS_SHAPELY or len(feats) < 2:
            return {"overlaps": [], "note": "Need at least 2 features and shapely for overlap detection"}

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
                overlaps.append({
                    "feature_indices": [ia, ib],
                    "overlaps": True,
                })
        return {"overlap_pairs": overlaps, "count": len(overlaps)}
