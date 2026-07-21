"""Road sampling helpers for Street View inspection sessions."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from pyproj import Geod

_GEOD = Geod(ellps="WGS84")


def _geometry(obj: dict[str, Any]) -> dict[str, Any]:
    if obj.get("type") == "Feature":
        return obj.get("geometry") or {}
    return obj


def _line_strings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    geom = _geometry(geometry)
    geom_type = geom.get("type")
    coords = geom.get("coordinates") or []
    if geom_type == "LineString":
        return [coords]
    if geom_type == "MultiLineString":
        return coords
    return []


def _segment_lengths(line: list[list[float]]) -> list[tuple[float, float, float]]:
    segments: list[tuple[float, float, float]] = []
    for start, end in zip(line, line[1:]):
        azimuth, _back_azimuth, distance = _GEOD.inv(start[0], start[1], end[0], end[1])
        if distance > 0:
            segments.append((azimuth, distance, 0.0))
    return segments


def _point_at(line: list[list[float]], distance_m: float) -> tuple[float, float]:
    remaining = distance_m
    for start, end in zip(line, line[1:]):
        azimuth, _back_azimuth, segment_m = _GEOD.inv(start[0], start[1], end[0], end[1])
        if segment_m <= 0:
            continue
        if remaining <= segment_m:
            lon, lat, _ = _GEOD.fwd(start[0], start[1], azimuth, remaining)
            return lat, lon
        remaining -= segment_m
    last = line[-1]
    return last[1], last[0]


def _line_length(line: list[list[float]]) -> float:
    total = 0.0
    for start, end in zip(line, line[1:]):
        _az, _back, distance = _GEOD.inv(start[0], start[1], end[0], end[1])
        total += max(distance, 0.0)
    return total


def sample_road_points(geometry: dict[str, Any], interval_m: float = 30.0) -> dict[str, Any]:
    """Sample points along a LineString or MultiLineString.

    Returns a session id plus ordered lat/lng points. The frontend downloads
    each point independently so it can show progress and remain responsive.
    """
    interval = max(5.0, min(float(interval_m or 30.0), 500.0))
    points: list[dict[str, Any]] = []
    sample_index = 0

    for line_index, line in enumerate(_line_strings(geometry)):
        if len(line) < 2:
            continue
        length = _line_length(line)
        if length <= 0:
            continue
        distances = [0.0]
        d = interval
        while d < length:
            distances.append(d)
            d += interval
        if distances[-1] != length:
            distances.append(length)

        for distance in distances:
            lat, lng = _point_at(line, distance)
            sample_index += 1
            points.append(
                {
                    "id": f"sv-sample-{sample_index}",
                    "line_index": line_index,
                    "distance_m": round(distance, 2),
                    "lat": lat,
                    "lng": lng,
                }
            )

    return {
        "session_id": f"road-sv-{uuid4().hex[:10]}",
        "interval_m": interval,
        "point_count": len(points),
        "points": points,
    }
