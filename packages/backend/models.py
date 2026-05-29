from pydantic import BaseModel
from typing import Optional, Any


class ArtifactCreate(BaseModel):
    title: str
    content: str = ""
    artifact_type: str = "note"
    format: str = "markdown"
    meta: Optional[Any] = None


class ArtifactUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    artifact_type: Optional[str] = None
    meta: Optional[Any] = None
