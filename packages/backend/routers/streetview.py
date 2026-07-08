"""HTTP endpoints for the integrated Street View workspace."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, Response

from streetview.viewer import StreetViewService

router = APIRouter()
service = StreetViewService()


class StreetViewImageRequest(BaseModel):
    lat: float
    lng: float
    radius: int = Field(50, ge=1, le=500)
    zoom: int = Field(3, ge=0, le=5)
    title: str | None = None
    notes: str | None = None


class RoadInspectionRequest(BaseModel):
    geometry: dict[str, Any]
    interval_m: float = Field(30.0, ge=5.0, le=500.0)


class StreetViewReportRequest(BaseModel):
    title: str = "Street View Report"
    images: list[dict[str, Any]]


@router.get("/meta")
async def streetview_meta(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(50, ge=1, le=500),
):
    try:
        return await run_in_threadpool(service.metadata, lat, lng, radius)
    except Exception as e:  # network / upstream change
        return JSONResponse(
            status_code=502,
            content={"found": False, "error": f"Street View lookup failed: {e}"},
        )


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
        meta, image, _cache_hit = await run_in_threadpool(
            service.image_bytes, lat, lng, radius, zoom
        )
        if not meta.get("found") or image is None:
            return JSONResponse(
                status_code=404, content={"error": "Panorama not found."}
            )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Panorama download failed: {e}"},
        )

    return Response(content=image, media_type="image/jpeg")


@router.post("/image")
async def streetview_image(req: StreetViewImageRequest):
    """Download a Street View image and save it as a project artifact."""
    try:
        return await run_in_threadpool(
            service.image_artifact,
            req.lat,
            req.lng,
            radius=req.radius,
            zoom=req.zoom,
            title=req.title,
            notes=req.notes,
        )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"found": False, "error": f"Street View image failed: {e}"},
        )


@router.post("/road-inspection")
async def road_inspection(req: RoadInspectionRequest):
    """Sample points along a road/polyline for asynchronous gallery downloads."""
    try:
        return await run_in_threadpool(service.road_points, req.geometry, req.interval_m)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"error": f"Could not sample road geometry: {e}"},
        )


@router.post("/report")
async def streetview_report(req: StreetViewReportRequest):
    """Create an editable report artifact from Street View images."""
    try:
        return await run_in_threadpool(service.report, req.title, req.images)
    except Exception as e:
        return JSONResponse(
            status_code=422,
            content={"error": f"Could not create Street View report: {e}"},
        )
