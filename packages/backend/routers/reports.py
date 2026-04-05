from fastapi import APIRouter
from pydantic import BaseModel
import json
import os

import httpx

OPENCODE_URL = os.environ.get("OPENCODE_URL", "http://localhost:4096")

router = APIRouter()


class ReportRequest(BaseModel):
    chat_history: list[dict] = []
    map_context: dict | None = None
    artifacts: list[dict] = []


class ReportResponse(BaseModel):
    markdown: str


REPORT_PROMPT = """Generate a structured urban planning report based on the provided conversation, map data, and project artifacts.

Format as clean, professional markdown with these sections:

# Planning Report

## Executive Summary
(2-3 paragraph overview of the planning discussion and key findings)

## Site Analysis
(Geographic context, existing conditions based on map data and layers)

## Key Findings
(Main points from the conversation and analysis)

## Recommendations
(Actionable next steps based on the discussion)

## Appendix
(Data sources, layer information, methodology notes)

Be specific, professional, and reference the actual data discussed. If map layers were loaded, describe their contents. If drawings were made, note what was drawn and where."""


@router.post("/generate", response_model=ReportResponse)
async def generate_report(request: ReportRequest):
    context_parts = []
    if request.map_context:
        context_parts.append(f"Map Context:\n```json\n{json.dumps(request.map_context, indent=2)}\n```")
    if request.chat_history:
        lines = []
        for m in request.chat_history:
            role = "User" if m.get("role") == "user" else "Assistant"
            lines.append(f"**{role}:** {m.get('content', '')}")
        context_parts.append("Conversation:\n" + "\n\n".join(lines))
    if request.artifacts:
        items = []
        for a in request.artifacts:
            items.append(f"- [{a.get('artifact_type', 'note')}] **{a.get('title', '')}**: {a.get('content', '')}")
        context_parts.append("Artifacts:\n" + "\n".join(items))

    full_prompt = REPORT_PROMPT + "\n\n---\n\n" + "\n\n".join(context_parts)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Create a temporary session for report generation
            sess = await client.post(f"{OPENCODE_URL}/session", json={"title": "Report"})
            sess.raise_for_status()
            session_id = sess.json()["id"]

            resp = await client.post(
                f"{OPENCODE_URL}/session/{session_id}/message",
                json={
                    "system": "You are a professional urban planning report writer. Generate well-structured, data-driven reports. Respond ONLY with the markdown report, no tool calls.",
                    "tools": {},  # disable all tools for report generation
                    "parts": [{"type": "text", "text": full_prompt}],
                },
            )
            resp.raise_for_status()
            parts = resp.json().get("parts", [])
            text = "".join(
                p.get("text", "") for p in parts if p.get("type") == "text"
            )
            return ReportResponse(markdown=text or "# Error\n\nNo content generated.")
    except Exception as e:
        return ReportResponse(markdown=f"# Error\n\n{str(e)}")
