"""
Reports router — direct OpenAI integration.

Generates a structured Markdown urban planning report from a chat history,
map context, and project artifacts. One non-streaming completion; no tools.
"""

import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter
from openai import AsyncOpenAI
from pydantic import BaseModel

_BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from tools.config import get_model as _get_model

router = APIRouter()

_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


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
        completion = await _client.chat.completions.create(
            model=_get_model(),
            messages=[
                {"role": "system", "content": REPORT_SYSTEM},
                {"role": "user", "content": full_prompt},
            ],
        )
        text = completion.choices[0].message.content or ""
        return ReportResponse(markdown=text or "# Error\n\nNo content generated.")
    except Exception as e:
        return ReportResponse(markdown=f"# Error\n\n{str(e)}")
