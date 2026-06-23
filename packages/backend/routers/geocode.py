"""Server-side geocoding proxy for the renderer search bar.

Tries Google Geocoding first (when ``GOOGLE_MAPS_API_KEY`` is set), then
falls back to Nominatim. Browsers can't set the ``User-Agent`` header from
JS, which violates OSM's usage policy and triggers rate limiting — so the
renderer always calls this endpoint instead of hitting either upstream
directly.

Response shape stays stable across upstreams so the UI does not branch:
``{"results": [{display_name, lat, lon, type, class, importance}]}``.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from tools.google import GoogleUnavailable, geocode_query as google_geocode_query, has_key as has_google_key
from tools import http as http_client

router = APIRouter()


@router.get("")
async def geocode(query: str = Query(..., description="Address or place name"), limit: int = 5):
    limit = max(1, min(int(limit), 20))

    # Tier 1: Google Geocoding (when key is set). Falls through silently on any
    # GoogleUnavailable — missing key, network blip, or non-OK status.
    if has_google_key():
        try:
            results = await google_geocode_query(query, limit=limit)
            if results:
                return {"results": results}
        except GoogleUnavailable:
            pass

    # Tier 2: Photon (komoot) — returns well-ranked city/town nodes, far better
    # than Nominatim for place-name lookups (e.g. "SAS Nagar" → Mohali city).
    # Results are sorted: place/admin features before highway/waterway/railway.
    _CLASS_RANK = {"place": 0, "boundary": 1, "natural": 2, "landuse": 3,
                   "highway": 9, "railway": 9, "waterway": 9}
    try:
        photon = await http_client.fetch_json(
            "https://photon.komoot.io/api/",
            namespace="photon",
            params={"q": query, "limit": limit},
        )
        features = (photon or {}).get("features", []) or []
        photon_results = []
        for feat in features:
            coords = (feat.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            lng, lat = coords[0], coords[1]
            props = feat.get("properties") or {}
            parts = [
                props.get("name"),
                props.get("city") or props.get("locality"),
                props.get("state"),
                props.get("country"),
            ]
            display_name = ", ".join(p for p in parts if p) or props.get("name", "")
            key = props.get("osm_key", "")
            photon_results.append((_CLASS_RANK.get(key, 5), {
                "display_name": display_name,
                "lat": float(lat),
                "lon": float(lng),
                "type": props.get("osm_value"),
                "class": key,
                "importance": None,
            }))
        photon_results.sort(key=lambda x: x[0])
        if photon_results:
            return {"results": [r for _, r in photon_results]}
    except Exception:
        pass

    # Tier 3: Nominatim fallback — sort by importance DESC so the most
    # significant administrative result leads (cities before bus stops).
    try:
        data = await http_client.fetch_json(
            "https://nominatim.openstreetmap.org/search",
            namespace="nominatim",
            params={"q": query, "format": "json", "limit": limit, "addressdetails": 1},
        )
        if not isinstance(data, list):
            return {"error": "Nominatim returned an unexpected response.", "results": []}
        data.sort(key=lambda r: float(r.get("importance") or 0), reverse=True)
        return {
            "results": [
                {
                    "display_name": r.get("display_name", ""),
                    "lat": float(r["lat"]) if r.get("lat") else None,
                    "lon": float(r["lon"]) if r.get("lon") else None,
                    "type": r.get("type"),
                    "class": r.get("class"),
                    "importance": r.get("importance"),
                }
                for r in data
            ]
        }
    except http_client.HTTPError as e:
        return {"error": str(e), "results": []}
    except Exception as e:
        return {"error": f"Unexpected error: {e}", "results": []}




@router.get("/reverse")
async def reverse_geocode(lat: float = Query(...), lng: float = Query(...)):
    """Resolve coordinates to a human address. Nominatim ``/reverse``; the
    server-side proxy exists because browsers cannot set the ``User-Agent``
    that OSM's usage policy requires. (Google reverse is not wired here yet —
    Nominatim is sufficient for a marker label and always keyless.)"""
    try:
        data = await http_client.fetch_json(
            "https://nominatim.openstreetmap.org/reverse",
            namespace="nominatim",
            params={
                "lat": lat,
                "lon": lng,
                "format": "json",
                "addressdetails": 1,
                "zoom": 18,
            },
        )
        if not isinstance(data, dict) or "display_name" not in data:
            return {"display_name": None, "lat": lat, "lon": lng}
        return {
            "display_name": data.get("display_name"),
            "lat": float(data["lat"]) if data.get("lat") else lat,
            "lon": float(data["lon"]) if data.get("lon") else lng,
            "type": data.get("type"),
            "class": data.get("category") or data.get("class"),
        }
    except http_client.HTTPError as e:
        return {"error": str(e), "display_name": None, "lat": lat, "lon": lng}
    except Exception as e:
        return {"error": f"Unexpected error: {e}", "display_name": None, "lat": lat, "lon": lng}
