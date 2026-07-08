import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from models import ArtifactCreate, ArtifactUpdate
from tools.artifact_store import save_artifact, read_artifact, delete_artifact, ARTIFACTS_DIR
from database import get_connection

router = APIRouter()


@router.get("")
async def list_artifacts():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, artifact_type, format, meta, "
            "SUBSTR(content, 1, 200) as preview, file_path, created_at, updated_at "
            "FROM artifacts ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("", status_code=201)
async def create_artifact(artifact: ArtifactCreate):
    """Create a text-based artifact via JSON body (backward-compatible route)."""
    try:
        result = save_artifact(
            title=artifact.title,
            artifact_type=artifact.artifact_type,
            format=artifact.format,
            content=artifact.content if artifact.content else None,
            meta=artifact.meta if isinstance(artifact.meta, dict) else None,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/upload", status_code=201)
async def upload_artifact(
    title: str = Form(...),
    artifact_type: str = Form("note"),
    format: str = Form("image"),
    content: str = Form(""),
    meta: str = Form(""),
    file: UploadFile = File(None),
):
    """Create an artifact via multipart form — intended for image uploads."""
    try:
        file_bytes = await file.read() if file else None
        file_ext = Path(file.filename).suffix.lstrip(".") if file and file.filename else None
        meta_dict = json.loads(meta) if meta else None
        result = save_artifact(
            title=title,
            artifact_type=artifact_type,
            format=format,
            content=content if content else None,
            file_bytes=file_bytes,
            file_ext=file_ext,
            meta=meta_dict,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{artifact_id}")
async def get_artifact_http(artifact_id: int):
    row = read_artifact(artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return row


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: int):
    row = read_artifact(artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    fmt = row.get("format", "markdown")

    if fmt == "image":
        fp = row.get("file_path")
        if not fp:
            raise HTTPException(status_code=404, detail="No file for this artifact")
        full_path = ARTIFACTS_DIR.parent / fp
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File missing from disk")
        mime = (json.loads(row["meta"]) if row.get("meta") else {}).get(
            "mime", "application/octet-stream"
        )
        return FileResponse(str(full_path), media_type=mime, filename=Path(fp).name)

    # Text formats: serve as their native file type
    ext_map = {
        "markdown": ("md", "text/markdown"),
        "table": ("csv", "text/csv"),
        "geojson": ("geojson", "application/geo+json"),
    }
    ext, media_type = ext_map.get(fmt, ("txt", "text/plain"))
    content = row.get("content", "")

    if fmt == "table":
        import io
        import csv

        data = json.loads(content) if content else {"columns": [], "rows": []}
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(data.get("columns", []))
        w.writerows(data.get("rows", []))
        content = buf.getvalue()

    title_safe = (
        (row.get("title") or "artifact").replace(" ", "_").replace("/", "-")[:40]
    )
    return Response(
        content=content.encode(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{title_safe}.{ext}"'},
    )


@router.get("/{artifact_id}/docx")
async def download_artifact_docx(artifact_id: int):
    import tempfile
    from tools.doc_exporter import markdown_to_docx
    from fastapi.responses import FileResponse

    row = read_artifact(artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    
    content = row.get("content", "")
    title = row.get("title") or "artifact"
    title_safe = title.replace(" ", "_").replace("/", "-")[:40]
    
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
        
    try:
        markdown_to_docx(content, tmp_path)
        return FileResponse(
            tmp_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{title_safe}.docx"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Word document: {str(e)}")


@router.get("/{artifact_id}/latex")
async def download_artifact_latex(artifact_id: int):
    import tempfile
    from tools.latex_exporter import save_latex

    row = read_artifact(artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content = row.get("content", "")
    title = row.get("title") or "Urban Planning Report"
    title_safe = title.replace(" ", "_").replace("/", "-")[:50]

    with tempfile.NamedTemporaryFile(suffix=".tex", delete=False, mode="w", encoding="utf-8") as tmp:
        tmp_path = tmp.name

    try:
        save_latex(content, tmp_path, title=title)
        return FileResponse(
            tmp_path,
            media_type="application/x-tex",
            filename=f"{title_safe}.tex"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate LaTeX document: {str(e)}")




@router.put("/{artifact_id}")
async def update_artifact(artifact_id: int, update: ArtifactUpdate):
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Artifact not found")

        fields, values = [], []
        if update.title is not None:
            fields.append("title = ?")
            values.append(update.title)
        if update.content is not None and existing["format"] != "image":
            fields.append("content = ?")
            values.append(update.content)
        if update.artifact_type is not None:
            fields.append("artifact_type = ?")
            values.append(update.artifact_type)
        if update.meta is not None:
            fields.append("meta = ?")
            values.append(
                json.dumps(update.meta) if not isinstance(update.meta, str) else update.meta
            )

        if fields:
            fields.append("updated_at = CURRENT_TIMESTAMP")
            values.append(artifact_id)
            conn.execute(
                f"UPDATE artifacts SET {', '.join(fields)} WHERE id = ?", values
            )
            conn.commit()

        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.delete("/{artifact_id}")
async def delete_artifact_http(artifact_id: int):
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if not existing:
        raise HTTPException(status_code=404, detail="Artifact not found")
    delete_artifact(artifact_id)
    return {"deleted": True}
