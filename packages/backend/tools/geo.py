"""
Geodesic geometry helpers — single source of truth for area, perimeter, and
buffer math. Uses pyproj's WGS84 ellipsoid for ground-truth values that handle
holes, MultiPolygons, and arbitrary latitudes correctly.
"""

from __future__ import annotations

from typing import Any

from pyproj import Geod, Transformer
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform as shapely_transform

_GEOD = Geod(ellps="WGS84")


def _to_geom(input_obj: Any):
    """Accept a GeoJSON Feature, FeatureCollection, geometry dict, or a raw ring
    of [lng,lat] pairs, and return a shapely geometry."""
    if isinstance(input_obj, list):
        # raw polygon ring
        if len(input_obj) >= 3:
            ring = list(input_obj)
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            return Polygon([(c[0], c[1]) for c in ring])
        raise ValueError("Need at least 3 coordinate pairs")

    if not isinstance(input_obj, dict):
        raise ValueError("Unsupported input")

    t = input_obj.get("type")
    if t == "FeatureCollection":
        feats = input_obj.get("features", [])
        if not feats:
            raise ValueError("Empty FeatureCollection")
        from shapely.ops import unary_union
        geoms = [shape(f.get("geometry")) for f in feats if f.get("geometry")]
        if not geoms:
            raise ValueError("FeatureCollection has no geometries")
        return unary_union(geoms)
    if t == "Feature":
        return shape(input_obj.get("geometry"))
    return shape(input_obj)


def geodesic_area_m2(input_obj: Any) -> float:
    """Geodesic area in m² (handles holes & MultiPolygon natively)."""
    geom = _to_geom(input_obj)
    if geom.is_empty:
        return 0.0
    area, _perimeter = _GEOD.geometry_area_perimeter(geom)
    return abs(area)


def geodesic_perimeter_m(input_obj: Any) -> float:
    """Geodesic perimeter in m (sum of all rings, outer + inner)."""
    geom = _to_geom(input_obj)
    if geom.is_empty:
        return 0.0
    _area, perimeter = _GEOD.geometry_area_perimeter(geom)
    return abs(perimeter)


def area_breakdown(input_obj: Any) -> dict:
    """Return area + perimeter in common urban-planning units."""
    geom = _to_geom(input_obj)
    if geom.is_empty:
        return {"area_m2": 0.0, "area_hectares": 0.0, "area_km2": 0.0,
                "area_acres": 0.0, "perimeter_m": 0.0, "perimeter_km": 0.0}
    area, perimeter = _GEOD.geometry_area_perimeter(geom)
    a = abs(area)
    p = abs(perimeter)
    return {
        "area_m2": round(a, 1),
        "area_hectares": round(a / 10000, 4),
        "area_km2": round(a / 1e6, 6),
        "area_acres": round(a / 4046.86, 4),
        "perimeter_m": round(p, 1),
        "perimeter_km": round(p / 1000, 4),
    }


def _utm_epsg_for(lon: float, lat: float) -> int:
    """Pick the right UTM zone for a coordinate. Northern hemisphere = 326xx,
    southern = 327xx. Good for buffer math in meters anywhere on Earth."""
    zone = int((lon + 180) / 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def geodesic_buffer(input_obj: Any, radius_m: float) -> dict:
    """Buffer a GeoJSON geometry by `radius_m` meters and return a GeoJSON
    geometry. Projects to UTM for the buffer and reprojects back to WGS84 lng/lat."""
    geom = _to_geom(input_obj)
    if geom.is_empty:
        raise ValueError("Empty geometry")

    rep = geom.representative_point()
    epsg = _utm_epsg_for(rep.x, rep.y)
    to_utm = Transformer.from_crs(4326, epsg, always_xy=True).transform
    to_wgs = Transformer.from_crs(epsg, 4326, always_xy=True).transform

    projected = shapely_transform(to_utm, geom)
    buffered = projected.buffer(radius_m)
    back = shapely_transform(to_wgs, buffered)
    return mapping(back)
