"""Report artifact helpers for Street View imagery."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from tools.artifact_store import save_artifact


def default_caption(item: dict[str, Any], index: int) -> str:
    """Build an editable planning caption for one Street View image."""
    address = item.get("address") or "Street View location"
    lat = item.get("lat")
    lng = item.get("lng")
    date = item.get("capture_date") or item.get("date")
    coords = f" ({lat:.5f}, {lng:.5f})" if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) else ""
    suffix = f", captured {date}" if date else ""
    return f"Figure {index}. {address}{coords}{suffix}."


def create_report_artifact(title: str, images: list[dict[str, Any]], workspace: str | None = None) -> dict[str, Any]:
    """Create an editable Markdown report containing Street View figures."""
    lines = [f"# {title}", "", f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}.", ""]
    for i, item in enumerate(images, start=1):
        artifact_id = item.get("artifact_id") or item.get("id")
        caption = item.get("caption") or default_caption(item, i)
        if artifact_id:
            lines.extend(
                [
                    f"![{caption}](http://localhost:8765/api/artifacts/{artifact_id}/download)",
                    "",
                    caption,
                    "",
                ]
            )
        else:
            lines.extend([caption, ""])
        notes = item.get("planner_notes") or item.get("notes")
        if notes:
            lines.extend([f"Planner notes: {notes}", ""])

    return save_artifact(
        title=title,
        artifact_type="report",
        format="markdown",
        content="\n".join(lines),
        meta={"source": "streetview", "image_count": len(images)},
        workspace=workspace,
    )
