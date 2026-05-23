"""
GIS MCP Server

Provides spatial analysis operations: buffer, centroid, convex hull, bounding box,
area/perimeter computation, point-in-polygon, nearest-feature, and isochrone
approximation using server-side geometry computation.

Uses Shapely for geometry, pyproj for geodesic measurements & UTM-based buffering.
All inputs are EPSG:4326 lng/lat.
"""

from __future__ import annotations

import asyncio

from llm.base import ToolDeclaration
from tools.geo import area_breakdown, geodesic_buffer

try:
    from shapely.geometry import MultiPoint, Point, Polygon, mapping, shape
    from shapely.ops import unary_union
except ImportError:
    HAS_SHAPELY = False
    shape = mapping = Point = MultiPoint = Polygon = unary_union = None
else:
    HAS_SHAPELY = True


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
                    "Useful for proximity analysis (e.g. 500m buffer around a school). "
                    "Uses geodesic UTM projection — accurate at any latitude."
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
                description=(
                    "Calculate geodesic area + perimeter of a polygon (in m², hectares, km², acres). "
                    "Handles holes (interior rings) and MultiPolygons correctly via the WGS84 ellipsoid."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "polygon": {
                            "type": "array",
                            "description": "Array of [longitude, latitude] coordinate pairs (single ring)",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "geojson": {
                            "type": "object",
                            "description": "Alternative: full GeoJSON Feature/geometry — use this for polygons with holes or MultiPolygons.",
                        },
                    },
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
        # Handlers are sync + CPU-bound — defer to a thread so we don't block the loop.
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
            return await asyncio.to_thread(handler, args)
        return {"error": f"Unknown tool: {tool_name}"}

    def _buffer(self, args: dict) -> dict:
        radius_m = float(args.get("radius_meters", 100))
        geojson_input = args.get("geojson")

        try:
            if geojson_input:
                geom_dict = geojson_input.get("geometry", geojson_input) if isinstance(geojson_input, dict) else geojson_input
                buffered = geodesic_buffer(geom_dict, radius_m)
                return {
                    "geojson": {
                        "type": "Feature",
                        "geometry": buffered,
                        "properties": {"buffer_meters": radius_m},
                    }
                }

            lat = args.get("lat")
            lng = args.get("lng")
            if lat is None or lng is None:
                return {"error": "Must provide either 'geojson' or both 'lat' and 'lng'"}
            buffered = geodesic_buffer({"type": "Point", "coordinates": [lng, lat]}, radius_m)
            return {
                "geojson": {
                    "type": "Feature",
                    "geometry": buffered,
                    "properties": {"center": [lng, lat], "buffer_meters": radius_m},
                }
            }
        except Exception as e:
            return {"error": str(e)}

    def _centroid(self, args: dict) -> dict:
        geojson = args.get("geojson", {})
        if HAS_SHAPELY:
            assert shape is not None
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
        polygon = args.get("polygon")
        geojson_input = args.get("geojson")

        try:
            if geojson_input:
                geom_dict = geojson_input.get("geometry", geojson_input) if isinstance(geojson_input, dict) else geojson_input
                return area_breakdown(geom_dict)
            if polygon:
                if len(polygon) < 3:
                    return {"error": "Need at least 3 coordinate pairs"}
                return area_breakdown(polygon)
            return {"error": "Provide either 'polygon' (ring) or 'geojson'"}
        except Exception as e:
            return {"error": str(e)}

    def _convex_hull(self, args: dict) -> dict:
        points = args.get("points", [])
        if len(points) < 3:
            return {"error": "Need at least 3 points"}

        if HAS_SHAPELY:
            assert MultiPoint is not None and mapping is not None
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
            assert Point is not None and Polygon is not None
            try:
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

        assert Polygon is not None and unary_union is not None and mapping is not None
        try:
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
