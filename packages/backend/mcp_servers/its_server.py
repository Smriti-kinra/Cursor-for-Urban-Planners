from __future__ import annotations
import json
import math
import httpx
from llm.base import ToolDeclaration

class ITSServer:
    description = "ITS traffic signal optimization and parking demand analytics"
    tool_names = {
        "optimize_traffic_signal",
        "analyze_parking_requirements",
    }

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="optimize_traffic_signal",
                description=(
                    "Calculate optimal traffic signal cycle length and green phase splits for an intersection "
                    "using Webster's Method. Inputs approach volumes, lane configs, and saturation flows, "
                    "returning phase timings, degree of saturation, delay, and level of service (LOS) estimates."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "intersection_name": {"type": "string", "description": "Optional name of the intersection."},
                        "lost_time_seconds": {
                            "type": "number",
                            "default": 4.0,
                            "description": "Total lost time (start-up + clearance) per phase in seconds. Defaults to 4.0."
                        },
                        "approaches": {
                            "type": "array",
                            "description": "List of approaching traffic lane groups.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "Approach identifier (e.g. 'Eastbound Left')."},
                                    "critical_volume_pcu_hr": {"type": "number", "description": "Peak critical design volume in Passenger Car Units per hour."},
                                    "saturation_flow_pcu_hr": {"type": "number", "default": 1800.0, "description": "Base saturation flow rate in PCU/hr/lane. Defaults to 1800."},
                                    "number_of_lanes": {"type": "integer", "default": 1, "description": "Number of lanes. Defaults to 1."}
                                },
                                "required": ["name", "critical_volume_pcu_hr"]
                            }
                        },
                        "phases_mapping": {
                            "type": "array",
                            "description": "Optional phase grouping. List of list of approach names, e.g. [['NB straight', 'SB straight'], ['EB straight', 'WB straight']]. If omitted, each approach is a separate phase.",
                            "items": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        }
                    },
                    "required": ["approaches"]
                }
            ),
            ToolDeclaration(
                name="analyze_parking_requirements",
                description=(
                    "Calculate required parking spaces (Equivalent Car Spaces - ECS) for a land-use layout. "
                    "If a bounding box is supplied, it scans OSM for existing parking lots and estimates the supply "
                    "adequacy, calculating any parking surplus or deficit."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "land_use_mix": {
                            "type": "array",
                            "description": "List of buildings or zoning uses.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {
                                        "type": "string",
                                        "enum": ["retail", "commercial", "office", "residential", "hotel", "cinema", "healthcare", "education"],
                                        "description": "Zoning use category."
                                    },
                                    "quantity": {"type": "number", "description": "Dimension quantity (GFA sqm for commercial, units for residential, rooms for hotel, beds for hospital, seats for cinema)."},
                                    "unit": {
                                        "type": "string",
                                        "enum": ["sqm_gfa", "units", "rooms", "seats", "beds"],
                                        "description": "Measurement unit."
                                    }
                                },
                                "required": ["category", "quantity", "unit"]
                            }
                        },
                        "supplied_spaces": {
                            "type": "integer",
                            "description": "Optional: Manually specified number of existing/proposed parking spaces."
                        },
                        "bylaw_standard": {
                            "type": "string",
                            "enum": ["chandigarh", "standard"],
                            "default": "chandigarh",
                            "description": "Bylaw code standard profiles to apply. Defaults to 'chandigarh'."
                        },
                        "bbox": {
                            "type": "object",
                            "description": "Optional bounding box {south, west, north, east} to fetch and count existing OSM parking lots.",
                            "properties": {
                                "south": {"type": "number"},
                                "west": {"type": "number"},
                                "north": {"type": "number"},
                                "east": {"type": "number"}
                            },
                            "required": ["south", "west", "north", "east"]
                        }
                    },
                    "required": ["land_use_mix"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "optimize_traffic_signal":
            return await self._optimize_signal(args)
        elif tool_name == "analyze_parking_requirements":
            return await self._analyze_parking(args)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _optimize_signal(self, args: dict) -> dict:
        intersection = args.get("intersection_name", "Unspecified Intersection")
        lost_time_base = float(args.get("lost_time_seconds", 4.0))
        approaches = args.get("approaches", [])
        phases_mapping = args.get("phases_mapping")

        if not approaches:
            return {"error": "At least one approach is required."}

        # Build lookup dict for approach variables
        approach_dict = {}
        for app in approaches:
            name = app["name"]
            volume = float(app["critical_volume_pcu_hr"])
            sat_flow = float(app.get("saturation_flow_pcu_hr", 1800.0))
            lanes = int(app.get("number_of_lanes", 1))
            capacity_base = sat_flow * lanes
            flow_ratio = volume / capacity_base if capacity_base > 0 else 0
            approach_dict[name] = {
                "name": name,
                "volume": volume,
                "sat_flow": sat_flow,
                "lanes": lanes,
                "capacity_base": capacity_base,
                "flow_ratio": flow_ratio
            }

        # Determine phase groups
        phases = []
        if phases_mapping:
            for idx, phase_apps in enumerate(phases_mapping):
                valid_apps = [name for name in phase_apps if name in approach_dict]
                if valid_apps:
                    phases.append({
                        "name": f"Phase {idx + 1}",
                        "approaches": valid_apps
                    })
        else:
            # Fallback: each approach is its own phase
            for name in approach_dict.keys():
                phases.append({
                    "name": f"Phase {len(phases) + 1}",
                    "approaches": [name]
                })

        num_phases = len(phases)
        total_lost_time = lost_time_base * num_phases

        # Calculate critical flow ratio per phase
        sum_y = 0.0
        for ph in phases:
            max_y = 0.0
            for app_name in ph["approaches"]:
                max_y = max(max_y, approach_dict[app_name]["flow_ratio"])
            ph["critical_y"] = max_y
            sum_y += max_y

        is_oversaturated = False
        warning = ""
        if sum_y >= 0.95:
            is_oversaturated = True
            warning = f"Warning: flow ratio Y={sum_y:.3f} indicates severe oversaturation (>= 0.95). Webster math capped to Y=0.90 for split calculation."
            sum_y = 0.90

        # Webster formula for optimal cycle length
        if sum_y < 1.0:
            optimal_cycle = (1.5 * total_lost_time + 5.0) / (1.0 - sum_y)
        else:
            optimal_cycle = 150.0

        # Cap cycle between 40s and 150s
        optimal_cycle = max(40.0, min(150.0, optimal_cycle))
        optimal_cycle_rounded = round(optimal_cycle)

        # Allocate green time splits (proportional to critical y)
        available_green = optimal_cycle_rounded - total_lost_time
        phase_timings = []
        
        for ph in phases:
            if sum_y > 0:
                g_split = (ph["critical_y"] / sum_y) * available_green
            else:
                g_split = available_green / num_phases
            
            g_split = max(5.0, round(g_split, 1)) # Min 5s green split
            ph["green_time"] = g_split
            
            phase_timings.append({
                "phase": ph["name"],
                "approaches": ph["approaches"],
                "critical_flow_ratio": round(ph["critical_y"], 3),
                "green_time_seconds": g_split
            })

        # Calculate delays and level of service per approach
        approach_reports = []
        for name, app in approach_dict.items():
            # Find which phase this approach runs in
            green_time = 5.0
            for ph in phases:
                if name in ph["approaches"]:
                    green_time = ph["green_time"]
                    break
            
            g_c = green_time / optimal_cycle_rounded
            cap = app["capacity_base"] * g_c
            x_saturation = app["volume"] / cap if cap > 0 else 9.9
            
            if x_saturation < 0.99:
                # Webster delay formula
                term1 = (optimal_cycle_rounded * (1.0 - g_c)**2) / (2.0 * (1.0 - g_c * x_saturation))
                term2 = (x_saturation**2) / (2.0 * app["volume"] * (1.0 - x_saturation) / 3600.0)
                delay = term1 + term2
            else:
                # Capped / Oversaturated delay formula
                term1 = (optimal_cycle_rounded * (1.0 - g_c)**2) / 2.0
                term2 = 1800.0 * (x_saturation - 1.0)
                delay = term1 + term2
                
            delay = max(0.1, round(delay, 1))
            
            # Level of Service (HCM Standards)
            if delay <= 10.0:
                los = "A"
            elif delay <= 20.0:
                los = "B"
            elif delay <= 35.0:
                los = "C"
            elif delay <= 55.0:
                los = "D"
            elif delay <= 80.0:
                los = "E"
            else:
                los = "F"

            approach_reports.append({
                "approach_name": name,
                "volume_pcu_hr": app["volume"],
                "lanes": app["lanes"],
                "capacity_pcu_hr": round(cap),
                "v_c_ratio": round(x_saturation, 2),
                "green_time": green_time,
                "delay_seconds_per_veh": delay,
                "level_of_service": los
            })

        # Generate report markdown
        report_sections = [
            f"# Traffic Signal Optimization Report: {intersection}\n",
            f"* **Optimal Cycle Length**: {optimal_cycle_rounded} seconds",
            f"* **Total Lost Time**: {total_lost_time} seconds (clearance/lost: {lost_time_base}s * {num_phases} phases)",
            f"* **Total Critical Flow Ratio (Y)**: {sum_y:.3f}",
            f"* **Oversaturated**: {'Yes' if is_oversaturated else 'No'}\n",
        ]
        if warning:
            report_sections.append(f"> [!WARNING]\n> {warning}\n")

        report_sections.extend([
            "## Optimal Phase Splits",
            "| Phase Name | Included Movements | Critical y | Green Time Split |",
            "| :--- | :--- | :--- | :--- |"
        ])
        for p in phase_timings:
            apps_str = ", ".join(p["approaches"])
            report_sections.append(f"| {p['phase']} | {apps_str} | {p['critical_flow_ratio']} | **{p['green_time_seconds']}s** |")

        report_sections.extend([
            "\n## Approach Capacity & Delay Analysis",
            "| Approach Name | Lane count | Demand (PCU/hr) | Capacity (PCU/hr) | V/C Ratio | Delay (s/veh) | LOS |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
        ])
        for r in approach_reports:
            report_sections.append(
                f"| {r['approach_name']} | {r['lanes']} | {r['volume_pcu_hr']:.0f} | {r['capacity_pcu_hr']} | {r['v_c_ratio']:.2f} | {r['delay_seconds_per_veh']:.1f} | **{r['level_of_service']}** |"
            )

        report_sections.append(
            "\n*Note: Level of Service (LOS) is graded from A (free flow, delay <= 10s) to F (gridlock, delay > 80s) according to Highway Capacity Manual standards.*"
        )
        
        report_markdown = "\n".join(report_sections)

        return {
            "status": "success",
            "intersection": intersection,
            "optimal_cycle_seconds": optimal_cycle_rounded,
            "lost_time_seconds": total_lost_time,
            "flow_ratio_y": sum_y,
            "phase_timings": phase_timings,
            "approach_analysis": approach_reports,
            "report_markdown": report_markdown
        }

    async def _analyze_parking(self, args: dict) -> dict:
        mix = args.get("land_use_mix", [])
        supplied_spaces = args.get("supplied_spaces")
        bylaw = args.get("bylaw_standard", "chandigarh")
        bbox = args.get("bbox")

        # BYLAW ECS TARGETS
        bylaw_rates = {
            "chandigarh": {
                "retail": 1.5,
                "commercial": 1.5,
                "office": 1.5,
                "residential": 2.0,
                "hotel": 1.0,
                "cinema": 0.1,
                "healthcare": 1.5,
                "education": 1.0
            },
            "standard": {
                "retail": 1.0,
                "commercial": 1.0,
                "office": 1.0,
                "residential": 1.0,
                "hotel": 0.5,
                "cinema": 0.05,
                "healthcare": 1.0,
                "education": 0.5
            }
        }

        rates = bylaw_rates.get(bylaw, bylaw_rates["chandigarh"])

        # Calculate demand
        detailed_demand = []
        total_demand = 0.0
        for item in mix:
            cat = item["category"]
            qty = float(item["quantity"])
            unit = item["unit"]
            rate = rates.get(cat, 1.0)
            
            if unit == "sqm_gfa" and cat in ("retail", "commercial", "office", "education"):
                demand = (qty / 100.0) * rate
                desc = f"{qty:,.0f} sqm GFA @ {rate:.2f} ECS/100 sqm"
            else:
                demand = qty * rate
                desc = f"{qty:,.0f} {unit} @ {rate:.2f} ECS/{unit[:-1]}"
                
            total_demand += demand
            detailed_demand.append({
                "category": cat,
                "quantity": qty,
                "unit": unit,
                "rate": rate,
                "required_ecs": round(demand),
                "description": desc
            })

        total_demand_rounded = round(total_demand)

        # Supply scan from OSM
        osm_spaces = 0
        supply_source = "User-supplied explicit value"
        parking_features_count = 0
        
        if bbox:
            s, w, n, e = bbox.get("south"), bbox.get("west"), bbox.get("north"), bbox.get("east")
            if None not in (s, w, n, e):
                query = f"""
[out:json][timeout:25];
(
  node["amenity"="parking"]({s},{w},{n},{e});
  way["amenity"="parking"]({s},{w},{n},{e});
  relation["amenity"="parking"]({s},{w},{n},{e});
);
out geom;
"""
                try:
                    url = "https://overpass-api.de/api/interpreter"
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(url, data={"data": query}, timeout=20.0)
                        data = resp.json()
                        elements = data.get("elements", [])
                        
                        parking_features_count = len(elements)
                        for el in elements:
                            tags = el.get("tags") or {}
                            if "capacity" in tags:
                                try:
                                    osm_spaces += int(tags["capacity"])
                                    continue
                                except ValueError:
                                    pass
                            
                            el_type = el.get("type")
                            if el_type in ("way", "relation"):
                                bounds = el.get("bounds", {})
                                if bounds:
                                    bs, bw, bn, be = bounds.get("minlat"), bounds.get("minlon"), bounds.get("maxlat"), bounds.get("maxlon")
                                    if bs and bw and bn and be:
                                        lat_mid = (bs + bn) / 2
                                        dy = (bn - bs) * 111000
                                        dx = (be - bw) * 111000 * math.cos(math.radians(lat_mid))
                                        area_sqm = dy * dx * 0.7
                                        osm_spaces += max(4, int(area_sqm / 25.0))
                                else:
                                    osm_spaces += 10
                            else:
                                osm_spaces += 10
                                
                    supply_source = f"OSM Bounding Box Scan ({parking_features_count} parking elements found)"
                except Exception as exc:
                    supply_source = f"OSM scan failed ({str(exc)}), falling back to user supply."

        if supplied_spaces is None:
            supplied_spaces = osm_spaces
        else:
            supply_source = "User-supplied explicit value"

        balance = supplied_spaces - total_demand_rounded
        adequacy_pct = round((supplied_spaces / total_demand_rounded) * 100) if total_demand_rounded > 0 else 100

        # Generate report
        report_sections = [
            f"# Parking Requirements & Adequacy Report\n",
            f"* **Standard Applied**: {bylaw.upper()} Bylaws Profile",
            f"* **Calculated Parking Demand**: **{total_demand_rounded} ECS**",
            f"* **Identified Parking Supply**: **{supplied_spaces} ECS** ({supply_source})",
            f"* **Net Balance**: **{'+' if balance >= 0 else ''}{balance} spaces** ({'Surplus' if balance >= 0 else 'Deficit'})",
            f"* **Supply Adequacy**: **{adequacy_pct}%**\n"
        ]

        if balance < 0:
            report_sections.append(
                f"> [!CAUTION]\n> **Parking Deficit Detected!** The current site plan is short by {-balance} parking spaces. "
                "Consider increasing parking structure spaces or implementing shared-parking strategies.\n"
            )
        else:
            report_sections.append(
                f"> [!NOTE]\n> **Sufficient Parking Supply.** The site satisfies the {bylaw.upper()} parking criteria.\n"
            )

        report_sections.extend([
            "## Land-Use Parking Demand Breakdown",
            "| Land-Use Category | Dimension / Quantity | Multiplier | Required ECS | Design Details |",
            "| :--- | :--- | :--- | :---: | :--- |"
        ])
        for d in detailed_demand:
            report_sections.append(
                f"| {d['category'].capitalize()} | {d['quantity']:,} | {d['rate']:.2f} | {d['required_ecs']} | {d['description']} |"
            )

        report_markdown = "\n".join(report_sections)

        return {
            "status": "success",
            "bylaw_standard": bylaw,
            "total_demand_ecs": total_demand_rounded,
            "supplied_spaces_ecs": supplied_spaces,
            "net_balance_ecs": balance,
            "adequacy_percentage": adequacy_pct,
            "demand_breakdown": detailed_demand,
            "report_markdown": report_markdown
        }
