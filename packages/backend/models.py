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


class ArtifactResponse(BaseModel):
    id: int
    title: str
    content: str
    artifact_type: str
    created_at: str
    updated_at: str


class ChatMessage(BaseModel):
    role: str
    content: str


class FileItem(BaseModel):
    name: str
    path: str
    is_directory: bool
    children: Optional[list] = None
