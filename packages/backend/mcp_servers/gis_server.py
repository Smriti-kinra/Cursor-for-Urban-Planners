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
import math

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


def _haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Great-circle distance in meters between two lng/lat points."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _to_shapes(obj):
    """Coerce a GeoJSON Feature, FeatureCollection, geometry dict, or a list of
    any of those into a flat list of (shapely_geom, properties) tuples."""
    if obj is None:
        return []
    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(_to_shapes(item))
        return out
    if not isinstance(obj, dict):
        return []
    t = obj.get("type")
    if t == "FeatureCollection":
        out = []
        for f in obj.get("features", []):
            out.extend(_to_shapes(f))
        return out
    if t == "Feature":
        geom = obj.get("geometry")
        if not geom:
            return []
        return [(shape(geom), obj.get("properties") or {})]
    # bare geometry dict
    if "coordinates" in obj or t == "GeometryCollection":
        return [(shape(obj), {})]
    return []


def _feature(geom, properties=None) -> dict:
    return {"type": "Feature", "geometry": mapping(geom), "properties": properties or {}}


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
        "gis_intersection",
        "gis_difference",
        "gis_clip",
        "gis_dissolve",
        "gis_nearest",
        "gis_spatial_join",
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
            ToolDeclaration(
                name="gis_intersection",
                description=(
                    "Geometric intersection (overlap) of two geometries A and B. Returns the "
                    "GeoJSON of the area they share — e.g. the part of a flood zone that falls "
                    "inside a ward. Each input is a GeoJSON Feature/FeatureCollection/geometry."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "a": {"type": "object", "description": "First geometry (GeoJSON)."},
                        "b": {"type": "object", "description": "Second geometry (GeoJSON)."},
                    },
                    "required": ["a", "b"],
                },
            ),
            ToolDeclaration(
                name="gis_difference",
                description=(
                    "Geometric difference A − B: the part of A NOT covered by B (e.g. land in a "
                    "district outside any park). Each input is a GeoJSON Feature/FeatureCollection/geometry."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "a": {"type": "object", "description": "Geometry to subtract from (GeoJSON)."},
                        "b": {"type": "object", "description": "Geometry to subtract (GeoJSON)."},
                    },
                    "required": ["a", "b"],
                },
            ),
            ToolDeclaration(
                name="gis_clip",
                description=(
                    "Clip a layer (FeatureCollection) to a clip polygon, keeping only the parts "
                    "inside it and preserving each feature's properties. Use to crop OSM/imported "
                    "data to a study-area boundary."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "features": {"type": "object", "description": "GeoJSON FeatureCollection (or Feature) to clip."},
                        "clip": {"type": "object", "description": "Clip polygon as GeoJSON Feature/geometry."},
                    },
                    "required": ["features", "clip"],
                },
            ),
            ToolDeclaration(
                name="gis_dissolve",
                description=(
                    "Dissolve (merge) the features of a layer into one geometry, or — if "
                    "'group_by' names a property — into one geometry per distinct value of that "
                    "property (e.g. dissolve parcels into zoning districts by zone_code). Returns "
                    "a FeatureCollection with the dissolved group value and area on each feature."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "features": {"type": "object", "description": "GeoJSON FeatureCollection to dissolve."},
                        "group_by": {"type": "string", "description": "Optional property name to group by before merging."},
                    },
                    "required": ["features"],
                },
            ),
            ToolDeclaration(
                name="gis_nearest",
                description=(
                    "Find the nearest feature(s) in a layer to a point, with geodesic distance in "
                    "meters. Use for 'closest hospital/bus stop to here'. Returns up to 'k' results "
                    "sorted by distance, each with its properties."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "point_lat": {"type": "number"},
                        "point_lng": {"type": "number"},
                        "features": {"type": "object", "description": "GeoJSON FeatureCollection to search."},
                        "k": {"type": "number", "description": "How many nearest to return (default 1)."},
                    },
                    "required": ["point_lat", "point_lng", "features"],
                },
            ),
            ToolDeclaration(
                name="gis_spatial_join",
                description=(
                    "Spatial join: tag each point in a point layer with the properties of the "
                    "polygon that contains it (e.g. label each school with the ward it sits in). "
                    "Returns the point FeatureCollection with the joined polygon properties merged "
                    "into each point under the given prefix."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "points": {"type": "object", "description": "GeoJSON FeatureCollection of points."},
                        "polygons": {"type": "object", "description": "GeoJSON FeatureCollection of polygons to join from."},
                        "prefix": {"type": "string", "description": "Prefix for joined property keys (default 'zone_')."},
                    },
                    "required": ["points", "polygons"],
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
            "gis_intersection": self._intersection,
            "gis_difference": self._difference,
            "gis_clip": self._clip,
            "gis_dissolve": self._dissolve,
            "gis_nearest": self._nearest,
            "gis_spatial_join": self._spatial_join,
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

    # ── Overlay + relational ops (Phase 5) ──

    def _intersection(self, args: dict) -> dict:
        if not HAS_SHAPELY:
            return {"error": "Shapely not installed"}
        try:
            a = unary_union([g for g, _ in _to_shapes(args.get("a"))])
            b = unary_union([g for g, _ in _to_shapes(args.get("b"))])
            if a.is_empty or b.is_empty:
                return {"error": "Both 'a' and 'b' geometries are required"}
            inter = a.intersection(b)
            if inter.is_empty:
                return {"intersects": False, "message": "Geometries do not overlap"}
            out = {"geojson": _feature(inter, {"op": "intersection"}), "intersects": True}
            try:
                out["area"] = area_breakdown(mapping(inter))
            except Exception:
                pass
            return out
        except Exception as e:
            return {"error": str(e)}

    def _difference(self, args: dict) -> dict:
        if not HAS_SHAPELY:
            return {"error": "Shapely not installed"}
        try:
            a = unary_union([g for g, _ in _to_shapes(args.get("a"))])
            b = unary_union([g for g, _ in _to_shapes(args.get("b"))])
            if a.is_empty:
                return {"error": "'a' geometry is required"}
            diff = a.difference(b)
            if diff.is_empty:
                return {"empty": True, "message": "B fully covers A; nothing remains"}
            out = {"geojson": _feature(diff, {"op": "difference"})}
            try:
                out["area"] = area_breakdown(mapping(diff))
            except Exception:
                pass
            return out
        except Exception as e:
            return {"error": str(e)}

    def _clip(self, args: dict) -> dict:
        if not HAS_SHAPELY:
            return {"error": "Shapely not installed"}
        try:
            clip_shapes = _to_shapes(args.get("clip"))
            if not clip_shapes:
                return {"error": "A 'clip' polygon is required"}
            clip_geom = unary_union([g for g, _ in clip_shapes])
            features = []
            for geom, props in _to_shapes(args.get("features")):
                try:
                    piece = geom.intersection(clip_geom)
                except Exception:
                    continue
                if not piece.is_empty:
                    features.append(_feature(piece, props))
            return {
                "geojson": {"type": "FeatureCollection", "features": features},
                "kept": len(features),
            }
        except Exception as e:
            return {"error": str(e)}

    def _dissolve(self, args: dict) -> dict:
        if not HAS_SHAPELY:
            return {"error": "Shapely not installed"}
        try:
            shapes = _to_shapes(args.get("features"))
            if not shapes:
                return {"error": "A 'features' FeatureCollection is required"}
            group_by = args.get("group_by")
            features = []
            if group_by:
                groups: dict = {}
                for geom, props in shapes:
                    key = props.get(group_by, "")
                    groups.setdefault(key, []).append(geom)
                for key, geoms in groups.items():
                    merged = unary_union(geoms)
                    feat = _feature(merged, {group_by: key})
                    try:
                        feat["properties"]["area_m2"] = area_breakdown(mapping(merged)).get("area_m2")
                    except Exception:
                        pass
                    features.append(feat)
            else:
                merged = unary_union([g for g, _ in shapes])
                feat = _feature(merged, {"dissolved": len(shapes)})
                try:
                    feat["properties"]["area_m2"] = area_breakdown(mapping(merged)).get("area_m2")
                except Exception:
                    pass
                features.append(feat)
            return {
                "geojson": {"type": "FeatureCollection", "features": features},
                "group_count": len(features),
            }
        except Exception as e:
            return {"error": str(e)}

    def _nearest(self, args: dict) -> dict:
        if not HAS_SHAPELY:
            return {"error": "Shapely not installed"}
        try:
            plat = float(args.get("point_lat"))
            plng = float(args.get("point_lng"))
            k = max(1, int(args.get("k", 1)))
            results = []
            for geom, props in _to_shapes(args.get("features")):
                # Distance from the query point to the feature's nearest point,
                # measured geodesically via the representative point of the
                # closest vertex set. For points this is exact; for lines/polys
                # we use the geometry's nearest coordinate.
                try:
                    rep = geom.interpolate(geom.project(Point(plng, plat))) \
                        if geom.geom_type in ("LineString", "MultiLineString") \
                        else (geom if geom.geom_type == "Point" else geom.centroid
                              if not geom.contains(Point(plng, plat)) else Point(plng, plat))
                except Exception:
                    rep = geom.centroid
                dist = _haversine_m(plng, plat, rep.x, rep.y)
                results.append({"distance_m": round(dist, 1), "properties": props,
                                "lat": round(rep.y, 6), "lng": round(rep.x, 6)})
            results.sort(key=lambda r: r["distance_m"])
            return {"nearest": results[:k], "searched": len(results)}
        except Exception as e:
            return {"error": str(e)}

    def _spatial_join(self, args: dict) -> dict:
        if not HAS_SHAPELY:
            return {"error": "Shapely not installed"}
        try:
            polys = _to_shapes(args.get("polygons"))
            prefix = args.get("prefix") or "zone_"
            out_features = []
            joined = 0
            for geom, props in _to_shapes(args.get("points")):
                pt = geom if geom.geom_type == "Point" else geom.centroid
                merged_props = dict(props)
                for poly, pprops in polys:
                    try:
                        if poly.contains(pt):
                            for k, v in (pprops or {}).items():
                                merged_props[f"{prefix}{k}"] = v
                            joined += 1
                            break
                    except Exception:
                        continue
                out_features.append(_feature(pt, merged_props))
            return {
                "geojson": {"type": "FeatureCollection", "features": out_features},
                "points": len(out_features),
                "joined": joined,
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
