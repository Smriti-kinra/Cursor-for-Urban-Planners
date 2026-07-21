"""Small file cache for downloaded Street View panoramas."""
from __future__ import annotations

import re
from pathlib import Path

from tools.artifact_store import ARTIFACTS_DIR

CACHE_DIR = ARTIFACTS_DIR / "streetview_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_key(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)[:180] or "streetview"


def cache_path(pano_id: str, zoom: int) -> Path:
    """Return the cache path for a panorama and zoom level."""
    return CACHE_DIR / f"{_safe_key(pano_id)}-z{zoom}.jpg"


def read_cached_image(pano_id: str | None, zoom: int) -> bytes | None:
    """Return cached JPEG bytes when present."""
    if not pano_id:
        return None
    path = cache_path(pano_id, zoom)
    if not path.exists():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def write_cached_image(pano_id: str | None, zoom: int, data: bytes) -> None:
    """Write JPEG bytes into the cache, ignoring disk failures."""
    if not pano_id:
        return
    try:
        cache_path(pano_id, zoom).write_bytes(data)
    except OSError:
        pass
