"""Street View lookup and download functions."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from aiohttp import ClientSession as _ClientSession
from streetlevel import streetview

from .cache import read_cached_image, write_cached_image
from .metadata import StreetViewMetadata, metadata_from_pano

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def patch_streetlevel_user_agent() -> None:
    """Give streetlevel's tile downloader a browser-like User-Agent.

    streetlevel 0.12.x creates an aiohttp ClientSession without headers, and
    Google's public tile endpoint rejects those requests with 403 responses.
    """
    if getattr(_ClientSession, "_streetview_ua_patched", False):
        return

    original_init = _ClientSession.__init__

    def clientsession_init(self: Any, *args: Any, **kwargs: Any) -> None:
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("User-Agent", _USER_AGENT)
        kwargs["headers"] = headers
        original_init(self, *args, **kwargs)

    _ClientSession.__init__ = clientsession_init  # type: ignore[assignment]
    _ClientSession._streetview_ua_patched = True  # type: ignore[attr-defined]


patch_streetlevel_user_agent()


def find_panorama(lat: float, lng: float, radius: int = 50) -> Any | None:
    """Find the nearest panorama to a coordinate."""
    return streetview.find_panorama(lat, lng, radius=radius)


def lookup_metadata(lat: float, lng: float, radius: int = 50) -> StreetViewMetadata:
    """Return metadata for the nearest panorama."""
    return metadata_from_pano(find_panorama(lat, lng, radius))


def panorama_jpeg(lat: float, lng: float, radius: int = 50, zoom: int = 3) -> tuple[StreetViewMetadata, bytes | None, bool]:
    """Return nearest panorama metadata, JPEG bytes, and cache-hit flag."""
    pano = find_panorama(lat, lng, radius)
    meta = metadata_from_pano(pano)
    if pano is None or not meta.pano_id:
        return meta, None, False

    cached = read_cached_image(meta.pano_id, zoom)
    if cached:
        return meta, cached, True

    image = streetview.get_panorama(pano, zoom)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    data = buf.getvalue()
    write_cached_image(meta.pano_id, zoom, data)
    return meta, data, False


def artifact_metadata(meta: StreetViewMetadata, notes: str | None = None) -> dict[str, Any]:
    """Return normalized artifact metadata for a Street View image."""
    return {
        "source": "streetview",
        "pano_id": meta.pano_id,
        "lat": meta.lat,
        "lng": meta.lon,
        "address": meta.address,
        "capture_date": meta.date,
        "heading": meta.heading,
        "planner_notes": notes or "",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
