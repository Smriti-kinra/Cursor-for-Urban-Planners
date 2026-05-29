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

    # Tier 2: Nominatim (this server-side proxy is the reason the route exists —
    # browsers cannot set the User-Agent header that OSM's usage policy requires).
    try:
        data = await http_client.fetch_json(
            "https://nominatim.openstreetmap.org/search",
            namespace="nominatim",
            params={"q": query, "format": "json", "limit": limit, "addressdetails": 1},
        )
        if not isinstance(data, list):
            return {"error": "Nominatim returned an unexpected response.", "results": []}
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
