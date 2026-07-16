"""
routers/scenarios.py — HTTP endpoints that let the Scenario Builder panel
call backend scenario tools directly without going through the chat WebSocket.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from mcp_servers.scenario_server import ScenarioServer

router = APIRouter()
_server = ScenarioServer()


class AnalyzeRequest(BaseModel):
    bbox: dict[str, float]
    metric_toggles: dict[str, bool] | None = None


class GenerateRequest(BaseModel):
    context: str
    scenario_types: list[str] | None = None
    focus_area: str = "mixed"
    baseline_metrics: dict[str, Any] | None = None


class CompareRequest(BaseModel):
    scenarios: list[dict[str, Any]]
    criteria: list[str] | None = None
    baseline_metrics: dict[str, Any] | None = None


@router.post("/analyze")
async def analyze_area(body: AnalyzeRequest):
    """Fetch real OSM geospatial metrics for a bounding box."""
    args = {"bbox": body.bbox}
    if body.metric_toggles:
        args["metric_toggles"] = body.metric_toggles
    result = await _server.execute("analyze_area_for_scenarios", args)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/generate")
async def generate_scenarios(body: GenerateRequest):
    """Generate structured planning scenarios for a study area."""
    args = {
        "context": body.context,
        "focus_area": body.focus_area,
    }
    if body.scenario_types:
        args["scenario_types"] = body.scenario_types
    if body.baseline_metrics:
        args["baseline_metrics"] = body.baseline_metrics
    result = await _server.execute("generate_planning_scenarios", args)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/compare")
async def compare_scenarios(body: CompareRequest):
    """Compare scenarios using real baseline data or LLM-estimated scores."""
    args = {"scenarios": body.scenarios}
    if body.criteria:
        args["criteria"] = body.criteria
    if body.baseline_metrics:
        args["baseline_metrics"] = body.baseline_metrics
    result = await _server.execute("compare_scenarios", args)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/save-artifact")
async def save_scenario_artifact(body: dict):
    """Save a generated scenario report as a markdown artifact."""
    from tools.artifact_store import save_artifact
    title = body.get("title", "Planning Scenario Report")
    content = body.get("markdown", "")
    if not content:
        raise HTTPException(status_code=400, detail="markdown content is required")
    result = save_artifact(
        title=title,
        artifact_type="report",
        format="markdown",
        content=content,
    )
    return result
