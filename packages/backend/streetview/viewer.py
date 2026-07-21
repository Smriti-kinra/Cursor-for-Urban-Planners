"""High-level Street View service used by the HTTP router."""
from __future__ import annotations

from typing import Any

from tools.artifact_store import save_artifact

from .downloader import artifact_metadata, lookup_metadata, panorama_jpeg
from .gallery import sample_road_points
from .report import create_report_artifact


class StreetViewService:
    """Coordinates Street View lookup, downloads, artifacts, and reports."""

    def metadata(self, lat: float, lng: float, radius: int = 50) -> dict[str, Any]:
        """Return nearest panorama metadata."""
        return lookup_metadata(lat, lng, radius).to_dict()

    def image_bytes(self, lat: float, lng: float, radius: int = 50, zoom: int = 3) -> tuple[dict[str, Any], bytes | None, bool]:
        """Return nearest panorama JPEG bytes with metadata and cache flag."""
        meta, data, cache_hit = panorama_jpeg(lat, lng, radius, zoom)
        return meta.to_dict(), data, cache_hit

    def image_artifact(
        self,
        lat: float,
        lng: float,
        *,
        radius: int = 50,
        zoom: int = 3,
        title: str | None = None,
        notes: str | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        """Download a panorama and save it as an image artifact."""
        meta, data, cache_hit = panorama_jpeg(lat, lng, radius, zoom)
        if not meta.found or data is None:
            return {"found": False, "metadata": meta.to_dict()}

        label = title or meta.address or f"Street View {meta.lat:.5f}, {meta.lon:.5f}"
        artifact = save_artifact(
            title=label,
            artifact_type="streetview",
            format="image",
            file_bytes=data,
            file_ext="jpg",
            meta={**artifact_metadata(meta, notes), "cache_hit": cache_hit},
            workspace=workspace,
        )
        return {
            "found": True,
            "metadata": meta.to_dict(),
            "artifact": artifact,
            "artifact_id": artifact["id"],
            "download_url": f"/api/artifacts/{artifact['id']}/download",
            "cache_hit": cache_hit,
        }

    def road_points(self, geometry: dict[str, Any], interval_m: float = 30.0) -> dict[str, Any]:
        """Sample points for a road inspection session."""
        return sample_road_points(geometry, interval_m)

    def report(self, title: str, images: list[dict[str, Any]], workspace: str | None = None) -> dict[str, Any]:
        """Create an editable Markdown report artifact for Street View images."""
        return create_report_artifact(title, images, workspace=workspace)
