"""Directory listing endpoint.

Restricted to a user-supplied workspace root (sent as `workspace`) — the
target path must resolve inside that root. Without a workspace, only the
user's home directory tree is browsable. This prevents the loopback CORS
surface from being used to enumerate the filesystem.
"""

from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Query

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
