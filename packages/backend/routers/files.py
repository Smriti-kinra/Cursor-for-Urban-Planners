"""Directory listing endpoint.

Restricted to a user-supplied workspace root (sent as `workspace`) — the
target path must resolve inside that root. Without a workspace, only the
user's home directory tree is browsable. This prevents the loopback CORS
surface from being used to enumerate the filesystem.
"""

from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Query
from pydantic import BaseModel

from tools.vector_convert import (
    SUPPORTED_EXTS,
    ConversionError,
    convert_file,
    detect_csv_lat_lng,
)

router = APIRouter()


def _is_within(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


@router.get("")
async def list_files(
    path: str = Query(..., description="Directory path to list"),
    workspace: str | None = Query(None, description="Workspace root the path must live under"),
):
    try:
        target = Path(path).expanduser().resolve(strict=False)
    except Exception:
        return {"error": "Invalid path"}

    if workspace:
        try:
            root = Path(workspace).expanduser().resolve(strict=False)
        except Exception:
            return {"error": "Invalid workspace"}
    else:
        root = Path.home().resolve(strict=False)

    if not _is_within(target, root):
        return {"error": "Path is outside the allowed workspace"}

    if not target.exists() or not target.is_dir():
        return {"error": "Invalid directory path"}

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith("."):
                continue
            items.append({
                "name": entry.name,
                "path": str(entry),
                "is_directory": entry.is_dir(),
            })
    except PermissionError:
        return {"error": "Permission denied"}

    return {"items": items, "path": str(target)}


class ConvertRequest(BaseModel):
    path: str
    workspace: str
    lat_col: str | None = None
    lng_col: str | None = None


def _safe_resolve(path: str, workspace: str) -> tuple[Path | None, Path | None, str | None]:
    """Resolve `path` and ensure it lives under `workspace`. Returns
    (target, root, error)."""
    try:
        target = Path(path).expanduser().resolve(strict=False)
    except Exception:
        return None, None, "Invalid path"
    try:
        root = Path(workspace).expanduser().resolve(strict=False)
    except Exception:
        return None, None, "Invalid workspace"
    if not _is_within(target, root):
        return None, None, "Path is outside the allowed workspace"
    return target, root, None


@router.get("/convert/probe")
async def probe_convertible(
    path: str = Query(...),
    workspace: str = Query(...),
):
    """Pre-flight a file: confirm it's a supported vector format and, for CSVs,
    report the auto-detected lat/lng columns so the UI can confirm/override."""
    target, _root, err = _safe_resolve(path, workspace)
    if err:
        return {"error": err}
    if not target.exists() or not target.is_file():
        return {"error": "File not found"}
    ext = target.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        return {"error": f"Unsupported file type: {ext or '(none)'}", "supported": sorted(SUPPORTED_EXTS)}
    result: dict = {"path": str(target), "ext": ext, "is_csv": ext == ".csv"}
    if ext == ".csv":
        try:
            lat, lng = detect_csv_lat_lng(str(target))
            result["lat_col"] = lat
            result["lng_col"] = lng
        except ConversionError as e:
            result["error"] = str(e)
    return result


@router.post("/convert")
async def convert_to_geojson(req: ConvertRequest):
    """Convert a shapefile/GeoPackage/KML/KMZ/GPX/CSV to a WGS84 GeoJSON file
    written alongside the source inside the workspace, and return its path."""
    target, _root, err = _safe_resolve(req.path, req.workspace)
    if err:
        return {"error": err}
    if not target.exists() or not target.is_file():
        return {"error": "File not found"}

    try:
        fc = convert_file(str(target), lat_col=req.lat_col, lng_col=req.lng_col)
    except ConversionError as e:
        return {"error": str(e)}
    except Exception as e:  # defensive: DuckDB/IO surprises
        return {"error": f"Conversion failed: {e}"}

    source_crs = fc.pop("_source_crs", None)
    out_path = target.with_suffix(".geojson")
    # Don't clobber an existing geojson of the same stem (e.g. a real export);
    # write to <stem>.converted.geojson instead.
    if out_path.exists() and out_path != target:
        out_path = target.with_name(f"{target.stem}.converted.geojson")
    try:
        out_path.write_text(json.dumps(fc), encoding="utf-8")
    except OSError as e:
        return {"error": f"Could not write GeoJSON: {e}"}

    return {
        "path": str(out_path),
        "name": out_path.stem,
        "feature_count": len(fc.get("features", [])),
        "source_crs": source_crs,
    }
