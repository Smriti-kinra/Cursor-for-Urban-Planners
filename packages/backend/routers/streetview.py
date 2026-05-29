"""Street View imagery via the keyless ``streetlevel`` library.

``streetlevel`` scrapes Google's public Street View tile endpoint — no
``GOOGLE_MAPS_API_KEY`` required. Its calls are synchronous, so we run them
in a threadpool to avoid blocking the event loop.

Two endpoints:
- ``GET /meta``  — find the nearest panorama to a point (metadata only).
- ``GET /pano``  — download the panorama nearest a point as an
  equirectangular JPEG.

Two upstream quirks of ``streetlevel`` 0.12.x forced deviations from the
original plan (see PANO note below):

1. Google's tile endpoint (``streetviewpixels-pa.googleapis.com``) returns
   ``403 Forbidden`` for requests without a browser ``User-Agent``.
   ``streetlevel``'s async tile downloader creates a bare ``aiohttp``
   ``ClientSession`` with no UA, so every ``get_panorama`` call 403s out of
   the box. We patch a default UA onto ``ClientSession`` at import time.

2. ``streetview.find_panorama_by_id`` returns ``None`` for current
   panoramas (Google's pano-id metadata RPC reports NOT_FOUND for recent
   IDs; the library itself documents that pano IDs are unstable). Even when
   it does return, it does not populate the ``image_sizes`` / ``tile_size``
   fields that ``get_panorama`` requires. The reliable path is the radius
   lookup ``find_panorama(lat, lon)``, which both finds current panoramas
   and fully populates the download metadata. So ``/pano`` takes ``lat`` /
   ``lng`` and rediscovers the panorama there, rather than looking it up by
   id.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

# --- Quirk #1: give streetlevel's aiohttp downloader a browser User-Agent. ---
# Must run before any streetlevel call. Google's tile endpoint 403s requests
# without one. Patching ClientSession.__init__ is the least invasive hook:
# get_panorama() offers no session parameter to inject through.
from aiohttp import ClientSession as _ClientSession

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

if not getattr(_ClientSession, "_streetview_ua_patched", False):
    _orig_clientsession_init = _ClientSession.__init__

    def _clientsession_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("User-Agent", _USER_AGENT)
        kwargs["headers"] = headers
        _orig_clientsession_init(self, *args, **kwargs)

    _ClientSession.__init__ = _clientsession_init  # type: ignore[assignment]
    _ClientSession._streetview_ua_patched = True  # type: ignore[attr-defined]
# -----------------------------------------------------------------------------

from streetlevel import streetview  # noqa: E402  (must follow the UA patch)

router = APIRouter()


def _address_str(pano) -> str | None:
    addr = getattr(pano, "address", None)
    if not addr:
        return None
    try:
        # address is a list of LocalizedString with a .value attribute.
        parts = [getattr(a, "value", str(a)) for a in addr]
        return ", ".join(p for p in parts if p) or None
    except Exception:
        return None


@router.get("/meta")
async def streetview_meta(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(50, ge=1, le=500),
):
    try:
        pano = await run_in_threadpool(
            streetview.find_panorama, lat, lng, radius=radius
        )
    except Exception as e:  # network / upstream change
        return JSONResponse(
            status_code=502,
            content={"found": False, "error": f"Street View lookup failed: {e}"},
        )

    if pano is None:
        return {"found": False}

    return {
        "found": True,
        "pano_id": pano.id,
        "lat": pano.lat,
        "lon": pano.lon,
        "date": str(pano.date) if getattr(pano, "date", None) else None,
        "heading": getattr(pano, "heading", None),
        "address": _address_str(pano),
    }


@router.get("/pano")
async def streetview_pano(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(50, ge=1, le=500),
    zoom: int = Query(3, ge=0, le=5),
):
    """Download the panorama nearest ``(lat, lng)`` as an equirectangular JPEG.

    Takes lat/lng rather than a pano_id: ``find_panorama_by_id`` is unreliable
    for current panoramas and does not populate the size metadata required to
    download tiles (see module docstring). The frontend gets the coordinates
    from ``/meta``, so it can pass them straight through.
    """
    try:
        pano = await run_in_threadpool(
            streetview.find_panorama, lat, lng, radius=radius
        )
        if pano is None:
            return JSONResponse(
                status_code=404, content={"error": "Panorama not found."}
            )
        image = await run_in_threadpool(streetview.get_panorama, pano, zoom)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Panorama download failed: {e}"},
        )

    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return Response(content=buf.getvalue(), media_type="image/jpeg")
