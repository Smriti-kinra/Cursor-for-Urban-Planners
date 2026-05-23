"""Server-side proxy for Nominatim geocoding.

Browsers can't set the `User-Agent` header from JS, which violates OSM's
usage policy and triggers rate limiting. The renderer should call this
endpoint instead of hitting Nominatim directly.
"""

from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Query

router = APIRouter()


@router.get("")
async def geocode(query: str = Query(..., description="Address or place name"), limit: int = 5):
    limit = max(1, min(int(limit), 20))
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": limit, "addressdetails": 1},
                headers={"User-Agent": "CursorUrbanPlanners/1.0"},
            )
        if resp.status_code != 200 or not (resp.text or "").strip():
            return {"error": f"Nominatim returned status {resp.status_code} with empty body.",
                    "results": []}
        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            return {"error": "Nominatim returned a non-JSON response (rate-limit page).",
                    "results": []}
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
    except httpx.RequestError as e:
        return {"error": f"Network error: {e}", "results": []}
    except Exception as e:
        return {"error": f"Unexpected error: {e}", "results": []}
