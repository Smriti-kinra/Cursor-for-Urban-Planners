"""Metadata helpers for Street View panoramas."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class StreetViewMetadata:
    """Serializable description of a resolved panorama."""

    found: bool
    pano_id: str | None = None
    lat: float | None = None
    lon: float | None = None
    date: str | None = None
    heading: float | None = None
    address: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return metadata in the API shape already used by the renderer."""
        return asdict(self)


def address_str(pano: Any) -> str | None:
    """Return a readable address string from streetlevel's address object."""
    addr = getattr(pano, "address", None)
    if not addr:
        return None
    try:
        parts = [getattr(a, "value", str(a)) for a in addr]
        return ", ".join(p for p in parts if p) or None
    except Exception:
        return None


def metadata_from_pano(pano: Any | None) -> StreetViewMetadata:
    """Convert a streetlevel panorama object into API metadata."""
    if pano is None:
        return StreetViewMetadata(found=False)
    return StreetViewMetadata(
        found=True,
        pano_id=getattr(pano, "id", None),
        lat=getattr(pano, "lat", None),
        lon=getattr(pano, "lon", None),
        date=str(pano.date) if getattr(pano, "date", None) else None,
        heading=getattr(pano, "heading", None),
        address=address_str(pano),
    )
