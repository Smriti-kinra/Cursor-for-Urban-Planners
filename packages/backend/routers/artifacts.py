from fastapi import APIRouter, HTTPException
from models import ArtifactCreate, ArtifactUpdate
from database import get_connection

router = APIRouter()


@router.get("")
async def list_artifacts():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM artifacts ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@router.post("", status_code=201)
async def create_artifact(artifact: ArtifactCreate):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO artifacts (title, content, artifact_type) VALUES (?, ?, ?)",
        (artifact.title, artifact.content, artifact.artifact_type),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (cursor.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return dict(row)


@router.put("/{artifact_id}")
async def update_artifact(artifact_id: int, update: ArtifactUpdate):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Artifact not found")

    fields = []
    values = []
    if update.title is not None:
        fields.append("title = ?")
        values.append(update.title)
    if update.content is not None:
        fields.append("content = ?")
        values.append(update.content)
    if update.artifact_type is not None:
        fields.append("artifact_type = ?")
        values.append(update.artifact_type)

    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(artifact_id)
        conn.execute(f"UPDATE artifacts SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: int):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Artifact not found")
    conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
    conn.commit()
    conn.close()
    return {"deleted": True}
