from fastapi import APIRouter, Query
from pathlib import Path

router = APIRouter()


@router.get("")
async def list_files(path: str = Query(..., description="Directory path to list")):
    target = Path(path)
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
