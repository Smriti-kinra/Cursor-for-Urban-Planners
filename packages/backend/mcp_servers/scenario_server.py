from __future__ import annotations
import json
from pathlib import Path
from llm.base import ToolDeclaration


class ScenarioServer:
    description = "Planning Scenario Generator & Comparator"
    tool_names = {"generate_planning_scenarios", "compare_scenarios"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="generate_planning_scenarios",
                description=(
                    "Generate structured planning scenario alternatives for a given study area "
                    "and planning challenge. Produces a set of named scenarios (e.g. Baseline, "
                    "Compact Growth, Transit-Oriented, Green Corridor) each with a description, "
                    "key strategies, land-use mix, and projected metrics. Saves the scenario "
                    "comparison as a markdown artifact."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "context": {
                            "type": "string",
                            "description": "Description of the study area, planning challenge, or objective (e.g. 'Mohali Phase 8 mobility plan', 'Sector 17 mixed-use redevelopment')."
                        },
                        "scenario_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of scenario names to generate. Defaults to ['Baseline', 'Compact Growth', 'Transit-Oriented Development', 'Green Corridor']."
                        },
                        "focus_area": {
                            "type": "string",
                            "enum": ["mobility", "land_use", "zoning", "environment", "mixed"],
                            "description": "Planning domain to focus the scenario analysis on."
                        }
                    },
                    "required": ["context"]
                }
            ),
            ToolDeclaration(
                name="compare_scenarios",
                description=(
                    "Compare two or more planning scenarios across quantitative metrics "
                    "(e.g. estimated population capacity, transit coverage, green space ratio, "
                    "infrastructure cost, carbon footprint, walkability index). "
                    "Returns a structured comparison table and a recommendation."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "scenarios": {
                            "type": "array",
                            "description": "List of scenario objects to compare. Each must have 'name' and 'description' keys.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "metrics": {
                                        "type": "object",
                                        "description": "Optional dict of metric name → value for quantitative comparison."
                                    }
                                },
                                "required": ["name", "description"]
                            }
                        },
                        "criteria": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Evaluation criteria to score (e.g. ['sustainability', 'cost', 'equity', 'mobility']). Defaults to standard urban planning criteria."
                        }
                    },
                    "required": ["scenarios"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "generate_planning_scenarios":
            return await self._generate_planning_scenarios(args)
        if tool_name == "compare_scenarios":
            return await self._compare_scenarios(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _generate_planning_scenarios(self, args: dict) -> dict:
        context = args.get("context", "").strip()
        focus = args.get("focus_area", "mixed")
        scenario_types = args.get("scenario_types") or [
            "Baseline (Business as Usual)",
            "Compact Growth",
            "Transit-Oriented Development",
            "Green Corridor"
        ]

        if not context:
            return {"error": "context is required"}

        focus_labels = {
            "mobility": "transportation, roads, public transit, and pedestrian access",
            "land_use": "land-use allocation, floor-area ratios, mixed-use zoning, and density",
            "zoning": "zoning regulations, setbacks, building heights, and permitted uses",
            "environment": "green space, tree cover, stormwater, and climate resilience",
            "mixed": "mobility, land use, zoning, environment, and economic development"
        }
        focus_description = focus_labels.get(focus, focus_labels["mixed"])

        scenario_defs = {
            "Baseline (Business as Usual)": {
                "tagline": "Continuation of current trends with incremental improvements",
                "land_use": "Existing mix maintained; minor infill development",
                "mobility": "Incremental road widening; no major transit expansion",
                "density": "Low to medium; current FAR limits maintained",
                "green_space": "Existing parks preserved; no new green corridors",
                "cost_index": "Low",
                "risk": "Urban sprawl, traffic congestion, declining quality of life"
            },
            "Compact Growth": {
                "tagline": "High-density development concentrated in activity cores",
                "land_use": "Mixed-use nodes at intersections; vertical density allowed",
                "mobility": "Walkable blocks; cycling infrastructure; feeder bus routes",
                "density": "High; FAR 3.0–4.5 in core zones",
                "green_space": "Pocket parks integrated; rooftop greening mandated",
                "cost_index": "Medium",
                "risk": "Gentrification pressure; parking deficit if transit is insufficient"
            },
            "Transit-Oriented Development": {
                "tagline": "Growth shaped around high-frequency transit corridors",
                "land_use": "Mixed-use within 500m of transit stops; residential beyond",
                "mobility": "BRT/metro corridor as backbone; first/last mile focus",
                "density": "High near stations (FAR 4–6); tapering outward",
                "green_space": "Linear greenways along transit corridors",
                "cost_index": "High",
                "risk": "High infrastructure investment; equity concerns if fares are unaffordable"
            },
            "Green Corridor": {
                "tagline": "Ecological network integrated with urban fabric",
                "land_use": "30% land reserved for green; eco-sensitive zoning",
                "mobility": "Non-motorised transport priority; cycle superhighways",
                "density": "Low to medium; height limits near ecological buffers",
                "green_space": "Continuous green belt; tree canopy target >35%",
                "cost_index": "Medium",
                "risk": "Lower developable land; revenue constraints for municipalities"
            },
        }

        output_sections = [
            f"# Planning Scenarios: {context}\n",
            f"**Focus Area:** {focus_description.title()}\n",
            "---\n"
        ]

        scenarios_data = []
        for scenario_name in scenario_types:
            # Get template if name matches, else build a generic one
            template = None
            for key in scenario_defs:
                if key.lower() in scenario_name.lower() or scenario_name.lower() in key.lower():
                    template = scenario_defs[key]
                    break
            if not template:
                template = {
                    "tagline": f"Custom alternative strategy for {context}",
                    "land_use": "To be defined based on stakeholder inputs",
                    "mobility": "To be aligned with regional mobility plan",
                    "density": "As per zoning study",
                    "green_space": "Per environmental impact assessment",
                    "cost_index": "To be estimated",
                    "risk": "Requires further analysis"
                }

            scenarios_data.append({
                "name": scenario_name,
                "description": f"{template['tagline']}. Density: {template['density']}. Mobility: {template['mobility']}."
            })

            output_sections.extend([
                f"## Scenario: {scenario_name}\n",
                f"*{template['tagline']}*\n",
                "| Parameter | Details |",
                "|---|---|",
                f"| **Land Use Strategy** | {template['land_use']} |",
                f"| **Mobility Approach** | {template['mobility']} |",
                f"| **Density Target** | {template['density']} |",
                f"| **Green Space** | {template['green_space']} |",
                f"| **Relative Cost** | {template['cost_index']} |",
                f"| **Key Risks** | {template['risk']} |\n",
            ])

        # Comparison summary table
        output_sections.extend([
            "---\n",
            "## Scenario Comparison Matrix\n",
            "| Scenario | Density | Transit | Green | Cost | Equity |",
            "|---|---|---|---|---|---|",
        ])

        ratings = {
            "Baseline (Business as Usual)": ("Low", "Low", "Low", "Low", "Medium"),
            "Compact Growth": ("High", "Medium", "Medium", "Medium", "Medium"),
            "Transit-Oriented Development": ("High", "High", "Medium", "High", "Low"),
            "Green Corridor": ("Medium", "Low", "High", "Medium", "High"),
        }

        for scenario_name in scenario_types:
            rating = None
            for key in ratings:
                if key.lower() in scenario_name.lower() or scenario_name.lower() in key.lower():
                    rating = ratings[key]
                    break
            if not rating:
                rating = ("–", "–", "–", "–", "–")
            output_sections.append(
                f"| {scenario_name} | {rating[0]} | {rating[1]} | {rating[2]} | {rating[3]} | {rating[4]} |"
            )

        output_sections.extend([
            "\n---\n",
            "## Planner's Note\n",
            f"These scenarios represent a strategic decision framework for **{context}**. "
            "Each scenario involves trade-offs between density, mobility, environmental sustainability, "
            "and fiscal viability. A hybrid approach drawing from multiple scenarios is often the "
            "most pragmatic planning outcome.\n",
            "> **Recommended next step:** Present scenarios to stakeholders for participatory scoring "
            "before moving to master plan drafting."
        ])

        markdown_report = "\n".join(output_sections)

        return {
            "status": "success",
            "scenario_count": len(scenario_types),
            "scenarios": scenario_types,
            "scenarios_data": scenarios_data,
            "report_markdown": markdown_report,
            "note": "Save this to an artifact with create_artifact (format: markdown) to preserve the scenario comparison report."
        }

    async def _compare_scenarios(self, args: dict) -> dict:
        scenarios = args.get("scenarios", [])
        criteria = args.get("criteria") or [
            "Sustainability", "Infrastructure Cost", "Mobility", "Equity", "Economic Growth", "Resilience"
        ]

        if len(scenarios) < 2:
            return {"error": "At least 2 scenarios are required for comparison."}

        # Simple weighted scoring model
        default_scores = {
            "baseline": {"Sustainability": 2, "Infrastructure Cost": 9, "Mobility": 3, "Equity": 5, "Economic Growth": 4, "Resilience": 3},
            "compact": {"Sustainability": 7, "Infrastructure Cost": 6, "Mobility": 7, "Equity": 5, "Economic Growth": 8, "Resilience": 7},
            "transit": {"Sustainability": 8, "Infrastructure Cost": 4, "Mobility": 10, "Equity": 6, "Economic Growth": 9, "Resilience": 8},
            "green": {"Sustainability": 10, "Infrastructure Cost": 6, "Mobility": 5, "Equity": 8, "Economic Growth": 5, "Resilience": 9},
        }

        results = []
        for sc in scenarios:
            name = sc.get("name", "Unknown")
            provided_metrics = sc.get("metrics") or {}
            # Find closest default profile
            profile = None
            for key in default_scores:
                if key in name.lower():
                    profile = default_scores[key]
                    break
            if not profile:
                profile = {c: 5 for c in criteria}

            # Merge with provided metrics
            scores = {c: provided_metrics.get(c, profile.get(c, 5)) for c in criteria}
            total = sum(scores.values())
            results.append({
                "name": name,
                "description": sc.get("description", ""),
                "scores": scores,
                "total_score": total
            })

        # Sort by total score
        results.sort(key=lambda x: x["total_score"], reverse=True)
        winner = results[0]["name"]

        # Build comparison table
        header = "| Scenario | " + " | ".join(criteria) + " | **Total** |"
        separator = "|---|" + "|".join(["---"] * len(criteria)) + "|---|"
        rows = []
        for r in results:
            score_cells = " | ".join(str(r["scores"].get(c, "–")) for c in criteria)
            rows.append(f"| {r['name']} | {score_cells} | **{r['total_score']}** |")

        table = "\n".join([header, separator] + rows)

        return {
            "status": "success",
            "recommended_scenario": winner,
            "ranking": [r["name"] for r in results],
            "comparison_table_markdown": table,
            "note": f"Based on scoring across {len(criteria)} criteria. '{winner}' scored highest overall."
        }
