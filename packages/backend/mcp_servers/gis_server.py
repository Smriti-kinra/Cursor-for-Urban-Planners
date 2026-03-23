"""
GIS MCP Server

Provides spatial analysis operations: buffer, centroid, convex hull, bounding box,
area/perimeter computation, point-in-polygon, nearest-feature, and isochrone
approximation using server-side geometry computation.

Uses Shapely for geometry operations (no external API needed).
"""

from __future__ import annotations

import math
from llm.base import ToolDeclaration

try:
    from shapely.geometry import shape, mapping, Point, MultiPoint
    from shapely.ops import unary_union
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False


class GISServer:
    description = "Spatial analysis: buffer, area, centroid, convex hull, intersection, point-in-polygon"
    tool_names = {
        "gis_buffer",
        "gis_centroid",
        "gis_area",
        "gis_convex_hull",
        "gis_point_in_polygon",
        "gis_bounding_box",
        "gis_union",
    }

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="gis_buffer",
                description=(
                    "Create a buffer zone around a point or geometry. "
                    "Returns GeoJSON polygon that can be displayed with add_geojson. "
                    "Useful for proximity analysis (e.g. 500m buffer around a school)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Center latitude (for point buffer)"},
                        "lng": {"type": "number", "description": "Center longitude (for point buffer)"},
                        "radius_meters": {"type": "number", "description": "Buffer radius in meters"},
                        "geojson": {"type": "object", "description": "Optional: GeoJSON geometry to buffer instead of a point"},
                    },
                    "required": ["radius_meters"],
                },
            ),
            ToolDeclaration(
                name="gis_centroid",
                description="Calculate the centroid (center point) of a GeoJSON geometry",
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {"type": "object", "description": "A GeoJSON Feature or geometry"},
                    },
                    "required": ["geojson"],
                },
            ),
            ToolDeclaration(
                name="gis_area",
                description="Calculate area and perimeter of a polygon in m², hectares, km²",
                parameters={
                    "type": "object",
                    "properties": {
                        "polygon": {
                            "type": "array",
                            "description": "Array of [longitude, latitude] coordinate pairs",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                    "required": ["polygon"],
                },
            ),
            ToolDeclaration(
                name="gis_convex_hull",
                description="Calculate the convex hull of a set of points. Returns GeoJSON polygon.",
                parameters={
                    "type": "object",
                    "properties": {
                        "points": {
                            "type": "array",
                            "description": "Array of [longitude, latitude] pairs",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                    "required": ["points"],
                },
            ),
            ToolDeclaration(
                name="gis_point_in_polygon",
                description="Check if a point is inside a polygon",
                parameters={
                    "type": "object",
                    "properties": {
                        "point_lat": {"type": "number"},
                        "point_lng": {"type": "number"},
                        "polygon": {
                            "type": "array",
                            "description": "Polygon coordinates as [[lng,lat], ...]",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                    "required": ["point_lat", "point_lng", "polygon"],
                },
            ),
            ToolDeclaration(
                name="gis_bounding_box",
                description="Get the bounding box of a set of coordinates",
                parameters={
                    "type": "object",
                    "properties": {
                        "coordinates": {
                            "type": "array",
                            "description": "Array of [longitude, latitude] pairs",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                    "required": ["coordinates"],
                },
            ),
            ToolDeclaration(
                name="gis_union",
                description="Merge multiple polygons into a single geometry (dissolve boundaries)",
                parameters={
                    "type": "object",
                    "properties": {
                        "polygons": {
                            "type": "array",
                            "description": "Array of polygon coordinate arrays",
                            "items": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "number"}},
                            },
                        },
                    },
                    "required": ["polygons"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        dispatch = {
            "gis_buffer": self._buffer,
            "gis_centroid": self._centroid,
            "gis_area": self._area,
            "gis_convex_hull": self._convex_hull,
            "gis_point_in_polygon": self._point_in_polygon,
            "gis_bounding_box": self._bounding_box,
            "gis_union": self._union,
        }
        handler = dispatch.get(tool_name)
        if handler:
            return handler(args)
        return {"error": f"Unknown tool: {tool_name}"}

    def _buffer(self, args: dict) -> dict:
        radius_m = args.get("radius_meters", 100)
        radius_deg = radius_m / 111320.0

        geojson_input = args.get("geojson")
        if geojson_input and HAS_SHAPELY:
            try:
                geom = shape(geojson_input.get("geometry", geojson_input))
                buffered = geom.buffer(radius_deg)
                return {
                    "geojson": {
                        "type": "Feature",
                        "geometry": mapping(buffered),
                        "properties": {"buffer_meters": radius_m},
                    }
                }
            except Exception as e:
                return {"error": str(e)}

        lat = args.get("lat", 0)
        lng = args.get("lng", 0)
        steps = 64
        coords = []
        for i in range(steps + 1):
            angle = (i / steps) * 2 * math.pi
            dx = radius_deg * math.cos(angle) / math.cos(math.radians(lat))
            dy = radius_deg * math.sin(angle)
            coords.append([round(lng + dx, 6), round(lat + dy, 6)])

        return {
            "geojson": {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {"center": [lng, lat], "buffer_meters": radius_m},
            }
        }

    def _centroid(self, args: dict) -> dict:
        geojson = args.get("geojson", {})
        if HAS_SHAPELY:
            try:
                geom = shape(geojson.get("geometry", geojson))
                c = geom.centroid
                return {"lat": round(c.y, 6), "lng": round(c.x, 6)}
            except Exception as e:
                return {"error": str(e)}

        coords = self._extract_all_coords(geojson)
        if not coords:
            return {"error": "No coordinates found"}
        avg_lng = sum(c[0] for c in coords) / len(coords)
        avg_lat = sum(c[1] for c in coords) / len(coords)
        return {"lat": round(avg_lat, 6), "lng": round(avg_lng, 6)}

    def _area(self, args: dict) -> dict:
        polygon = args.get("polygon", [])
        if len(polygon) < 3:
            return {"error": "Need at least 3 coordinate pairs"}

        R = 6371000.0
        n = len(polygon)
        area = 0.0
        perimeter = 0.0

        for i in range(n):
            j = (i + 1) % n
            xi = math.radians(polygon[i][0]) * R * math.cos(math.radians(polygon[i][1]))
            yi = math.radians(polygon[i][1]) * R
            xj = math.radians(polygon[j][0]) * R * math.cos(math.radians(polygon[j][1]))
            yj = math.radians(polygon[j][1]) * R
            area += xi * yj - xj * yi

            dlat = math.radians(polygon[j][1] - polygon[i][1])
            dlon = math.radians(polygon[j][0] - polygon[i][0])
            a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(polygon[i][1])) * math.cos(math.radians(polygon[j][1])) * math.sin(dlon / 2) ** 2
            perimeter += R * 2 * math.asin(math.sqrt(a))

        area_m2 = abs(area) / 2
        return {
            "area_m2": round(area_m2, 1),
            "area_hectares": round(area_m2 / 10000, 4),
            "area_km2": round(area_m2 / 1e6, 6),
            "area_acres": round(area_m2 / 4046.86, 4),
            "perimeter_m": round(perimeter, 1),
            "perimeter_km": round(perimeter / 1000, 4),
        }

    def _convex_hull(self, args: dict) -> dict:
        points = args.get("points", [])
        if len(points) < 3:
            return {"error": "Need at least 3 points"}

        if HAS_SHAPELY:
            try:
                mp = MultiPoint([(p[0], p[1]) for p in points])
                hull = mp.convex_hull
                return {
                    "geojson": {
                        "type": "Feature",
                        "geometry": mapping(hull),
                        "properties": {"point_count": len(points)},
                    }
                }
            except Exception as e:
                return {"error": str(e)}

        return {"error": "Shapely not installed; convex hull requires shapely"}

    def _point_in_polygon(self, args: dict) -> dict:
        plat = args.get("point_lat", 0)
        plng = args.get("point_lng", 0)
        polygon = args.get("polygon", [])

        if HAS_SHAPELY:
            try:
                from shapely.geometry import Polygon
                poly = Polygon([(c[0], c[1]) for c in polygon])
                pt = Point(plng, plat)
                inside = poly.contains(pt)
                return {"inside": inside, "point": [plng, plat]}
            except Exception as e:
                return {"error": str(e)}

        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i][0], polygon[i][1]
            xj, yj = polygon[j][0], polygon[j][1]
            if ((yi > plat) != (yj > plat)) and (plng < (xj - xi) * (plat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return {"inside": inside, "point": [plng, plat]}

    def _bounding_box(self, args: dict) -> dict:
        coordinates = args.get("coordinates", [])
        if not coordinates:
            return {"error": "No coordinates provided"}
        lngs = [c[0] for c in coordinates]
        lats = [c[1] for c in coordinates]
        return {
            "south": min(lats),
            "west": min(lngs),
            "north": max(lats),
            "east": max(lngs),
        }

    def _union(self, args: dict) -> dict:
        polygons = args.get("polygons", [])
        if not polygons or len(polygons) < 2:
            return {"error": "Need at least 2 polygons"}

        if not HAS_SHAPELY:
            return {"error": "Shapely not installed; union requires shapely"}

        try:
            from shapely.geometry import Polygon
            geoms = [Polygon([(c[0], c[1]) for c in poly]) for poly in polygons]
            merged = unary_union(geoms)
            return {
                "geojson": {
                    "type": "Feature",
                    "geometry": mapping(merged),
                    "properties": {"polygon_count": len(polygons)},
                }
            }
        except Exception as e:
            return {"error": str(e)}

    def _extract_all_coords(self, geojson: dict) -> list:
        coords = []
        geom = geojson.get("geometry", geojson)
        t = geom.get("type", "")
        c = geom.get("coordinates", [])

        if t == "Point":
            coords.append(c)
        elif t in ("LineString", "MultiPoint"):
            coords.extend(c)
        elif t in ("Polygon", "MultiLineString"):
            for ring in c:
                coords.extend(ring)
        elif t == "MultiPolygon":
            for poly in c:
                for ring in poly:
                    coords.extend(ring)

        return coords
