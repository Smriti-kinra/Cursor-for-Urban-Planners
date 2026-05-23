from pydantic import BaseModel
from typing import Optional


class ArtifactCreate(BaseModel):
    title: str
    content: str
    artifact_type: str = "note"


class ArtifactUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    artifact_type: Optional[str] = None
