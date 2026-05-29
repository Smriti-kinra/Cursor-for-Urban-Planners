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
from fastapi.responses import StreamingResponse
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


STREAM_SYSTEM = (
    "You are a professional urban planning report writer. "
    "Generate a well-structured, data-driven report in clean Markdown. "
    "Use the provided conversation, map data, and artifacts as your primary source. "
    "Enrich your analysis with publicly available information about the location. "
    "Respond ONLY with the Markdown report. Always respond in English."
)

STREAM_REPORT_PROMPT = """Generate a comprehensive urban planning report based on the data below.

Structure the report with these sections:

# Urban Planning Report

## Executive Summary
(2-3 paragraph overview of the planning discussion, location, and key findings)

## Site Analysis
(Geographic context, existing conditions, basemap and layer data, drawn features, placed markers)

## Key Findings
(Main points from the conversation and analysis, enriched with current public data)

## Recommendations
(Actionable next steps based on the discussion and research)

## Appendix
(Data sources, layer descriptions, methodology notes, web sources consulted)

Be specific and professional. Reference the actual map data, drawn geometries, and conversation details provided.

---
"""


def _build_stream_prompt(request: ReportRequest) -> str:
    parts = [STREAM_REPORT_PROMPT]

    if request.map_context:
        ctx = request.map_context
        center = ctx.get("center", [])
        zoom = ctx.get("zoom", "")
        bounds = ctx.get("bounds", {})
        basemap = ctx.get("basemap", "")
        bookmarks = ctx.get("bookmarks", [])
        layers = ctx.get("layers", [])

        loc_lines = [f"**Center:** {center}", f"**Zoom:** {zoom}", f"**Basemap:** {basemap}"]
        if bounds:
            loc_lines.append(
                f"**Bounds:** W={bounds.get('west')}, S={bounds.get('south')}, "
                f"E={bounds.get('east')}, N={bounds.get('north')}"
            )
        parts.append("## Map Context\n" + "\n".join(loc_lines))

        if bookmarks:
            bm_lines = [
                f"- {b.get('name', '')}: bounds W={b.get('west')}, S={b.get('south')}, E={b.get('east')}, N={b.get('north')}"
                for b in bookmarks
            ]
            parts.append("### Bookmarks\n" + "\n".join(bm_lines))

        if layers:
            layer_lines = []
            for layer in layers:
                name = layer.get("name", "unnamed")
                count = layer.get("featureCount", 0)
                geom_types = ", ".join(layer.get("geometryTypes", []))
                props = ", ".join(layer.get("properties", []))
                visible = layer.get("visible", True)
                line = f"- **{name}** ({count} features, {geom_types}, visible={visible})"
                if props:
                    line += f"\n  Properties: {props}"
                geo = layer.get("geometry_data")
                if geo:
                    if isinstance(geo, list):
                        line += f"\n  Coordinates: {json.dumps(geo)}"
                    elif isinstance(geo, dict) and "bbox" in geo:
                        line += f"\n  Bounding box: {geo['bbox']}"
                layer_lines.append(line)
            parts.append("### Layers\n" + "\n".join(layer_lines))

    if request.chat_history:
        lines = []
        for m in request.chat_history:
            role = "User" if m.get("role") == "user" else "Assistant"
            content = m.get("content", "")
            if content:
                lines.append(f"**{role}:** {content}")
        if lines:
            parts.append("## Conversation\n" + "\n\n".join(lines))

    if request.artifacts:
        items = []
        for a in request.artifacts:
            t = a.get("artifact_type", "note")
            title = a.get("title", "")
            content = a.get("content", "")
            truncated = content[:500] + ("…" if len(content) > 500 else "")
            items.append(f"- [{t}] **{title}**: {truncated}")
        parts.append("## Artifacts\n" + "\n".join(items))

    return "\n\n".join(parts)


@router.post("/stream")
async def stream_report(request: ReportRequest):
    prompt = _build_stream_prompt(request)

    async def generate():
        try:
            got_text = False
            async with await _client.responses.create(
                model="o4-mini-deep-research",
                input=prompt,
                instructions=STREAM_SYSTEM,
                tools=[{"type": "web_search_preview"}],
                max_tool_calls=20,
                stream=True,
            ) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", None)

                    if event_type == "response.web_search_call.searching":
                        query = getattr(event, "query", "") or ""
                        if query:
                            data = json.dumps({"action": "search", "query": query})
                            yield f"event: tool_call\ndata: {data}\n\n"

                    elif event_type == "response.output_text.done":
                        text = getattr(event, "text", "") or ""
                        if text:
                            got_text = True
                            data = json.dumps({"markdown": text})
                            yield f"event: message\ndata: {data}\n\n"

            if not got_text:
                data = json.dumps({"detail": "No report text was generated."})
                yield f"event: error\ndata: {data}\n\n"
            else:
                yield "event: done\ndata: {}\n\n"

        except Exception as exc:
            data = json.dumps({"detail": str(exc)})
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
