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

REPORT_SYSTEM = (
    "You are a professional urban planning report writer. "
    "Generate well-structured, data-driven reports. "
    "Respond ONLY with the markdown report, no tool calls. Always respond in English."
)


async def _collect_response(session_id: str, prompt: str) -> str:
    """Send prompt via prompt_async and collect streamed text via SSE until session.idle."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{OPENCODE_URL}/session/{session_id}/prompt_async",
            json={
                "system": REPORT_SYSTEM,
                "parts": [{"type": "text", "text": prompt}],
            },
        )
        if resp.status_code != 204:
            return ""

    text = ""
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", f"{OPENCODE_URL}/event") as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                props = event.get("properties", {})
                if props.get("sessionID") != session_id:
                    continue

                etype = event.get("type", "")
                if etype == "message.part.delta" and props.get("field") == "text":
                    text += props.get("delta", "")
                elif etype in ("session.idle", "session.error"):
                    break

    return text


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
        async with httpx.AsyncClient(timeout=10.0) as client:
            sess = await client.post(f"{OPENCODE_URL}/session", json={"title": "Report"})
            sess.raise_for_status()
            session_id = sess.json()["id"]

        text = await _collect_response(session_id, full_prompt)
        return ReportResponse(markdown=text or "# Error\n\nNo content generated.")
    except Exception as e:
        return ReportResponse(markdown=f"# Error\n\n{str(e)}")
