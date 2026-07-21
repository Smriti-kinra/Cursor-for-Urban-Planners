from __future__ import annotations
import json
import math
from llm.base import ToolDeclaration


class EmissionsServer:
    description = "Tailpipe Emissions & Local Air Quality Box Model Solver"
    tool_names = {"estimate_scenario_emissions"}

    # Official vehicle emission factors (grams per km)
    # Categories: car, two_wheeler, auto_rickshaw, bus, walk_cycle
    # Fuels: petrol, diesel, cng, electric
    EMISSION_FACTORS = {
        "arai_bs6": {
            "car": {
                "petrol": {"co2": 150.0, "nox": 0.06, "pm": 0.005, "co": 1.0},
                "diesel": {"co2": 130.0, "nox": 0.08, "pm": 0.0045, "co": 0.5},
                "cng": {"co2": 110.0, "nox": 0.04, "pm": 0.001, "co": 0.6},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "two_wheeler": {
                "petrol": {"co2": 40.0, "nox": 0.10, "pm": 0.002, "co": 1.0},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "auto_rickshaw": {
                "cng": {"co2": 80.0, "nox": 0.15, "pm": 0.005, "co": 1.5},
                "diesel": {"co2": 90.0, "nox": 0.25, "pm": 0.05, "co": 1.0},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "bus": {
                "diesel": {"co2": 800.0, "nox": 6.0, "pm": 0.10, "co": 2.0},
                "cng": {"co2": 700.0, "nox": 4.0, "pm": 0.02, "co": 1.5},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "walk_cycle": {
                "walk": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            }
        },
        "arai_bs4": {
            "car": {
                "petrol": {"co2": 160.0, "nox": 0.08, "pm": 0.005, "co": 1.0},
                "diesel": {"co2": 140.0, "nox": 0.25, "pm": 0.025, "co": 0.5},
                "cng": {"co2": 120.0, "nox": 0.06, "pm": 0.002, "co": 0.6},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "two_wheeler": {
                "petrol": {"co2": 50.0, "nox": 0.15, "pm": 0.003, "co": 1.5},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "auto_rickshaw": {
                "cng": {"co2": 90.0, "nox": 0.20, "pm": 0.008, "co": 2.0},
                "diesel": {"co2": 100.0, "nox": 0.50, "pm": 0.09, "co": 1.5},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "bus": {
                "diesel": {"co2": 900.0, "nox": 9.0, "pm": 0.20, "co": 3.5},
                "cng": {"co2": 800.0, "nox": 6.0, "pm": 0.05, "co": 2.5},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "walk_cycle": {
                "walk": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            }
        },
        "eea_euro6": {
            "car": {
                "petrol": {"co2": 120.0, "nox": 0.06, "pm": 0.005, "co": 1.0},
                "diesel": {"co2": 105.0, "nox": 0.08, "pm": 0.0045, "co": 0.5},
                "cng": {"co2": 100.0, "nox": 0.04, "pm": 0.001, "co": 0.6},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "two_wheeler": {
                "petrol": {"co2": 35.0, "nox": 0.08, "pm": 0.001, "co": 1.0},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "auto_rickshaw": {
                "cng": {"co2": 70.0, "nox": 0.10, "pm": 0.003, "co": 1.0},
                "diesel": {"co2": 80.0, "nox": 0.20, "pm": 0.03, "co": 0.8},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "bus": {
                "diesel": {"co2": 750.0, "nox": 0.40, "pm": 0.01, "co": 1.5},
                "cng": {"co2": 650.0, "nox": 0.30, "pm": 0.005, "co": 1.0},
                "electric": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            },
            "walk_cycle": {
                "walk": {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0}
            }
        }
    }

    # Standard scenario templates for auto-generating splits if omitted
    SCENARIO_TEMPLATES = {
        "baseline": {
            "mode_share": {"car": 0.40, "two_wheeler": 0.35, "auto_rickshaw": 0.10, "bus": 0.10, "walk_cycle": 0.05},
            "fuel_mix": {"petrol": 0.60, "diesel": 0.30, "cng": 0.09, "electric": 0.01},
            "daily_trips": 100000.0,
            "avg_trip_length_km": 7.5
        },
        "compact": {
            "mode_share": {"car": 0.30, "two_wheeler": 0.30, "auto_rickshaw": 0.10, "bus": 0.20, "walk_cycle": 0.10},
            "fuel_mix": {"petrol": 0.50, "diesel": 0.25, "cng": 0.15, "electric": 0.10},
            "daily_trips": 90000.0,
            "avg_trip_length_km": 5.5
        },
        "transit": {
            "mode_share": {"car": 0.15, "two_wheeler": 0.15, "auto_rickshaw": 0.10, "bus": 0.40, "walk_cycle": 0.20},
            "fuel_mix": {"petrol": 0.40, "diesel": 0.15, "cng": 0.25, "electric": 0.20},
            "daily_trips": 95000.0,
            "avg_trip_length_km": 6.0
        },
        "green": {
            "mode_share": {"car": 0.20, "two_wheeler": 0.20, "auto_rickshaw": 0.10, "bus": 0.20, "walk_cycle": 0.30},
            "fuel_mix": {"petrol": 0.30, "diesel": 0.10, "cng": 0.20, "electric": 0.40},
            "daily_trips": 85000.0,
            "avg_trip_length_km": 5.0
        }
    }

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="estimate_scenario_emissions",
                description=(
                    "Estimate and compare road tailpipe emissions (CO2, PM2.5, NOx, CO) "
                    "across multiple urban planning scenarios. Translates PM emissions into "
                    "localized ambient PM2.5 concentration increments (ug/m3) using the Gifford-Hanna Box Model."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "scenarios": {
                            "type": "array",
                            "description": (
                                "List of scenarios to analyze. Each scenario can have: 'name' (required), "
                                "'daily_trips' (optional), 'avg_trip_length_km' (optional), "
                                "'mode_share' (optional: dict mapping car, two_wheeler, auto_rickshaw, bus, walk_cycle to fractions), "
                                "and 'fuel_mix' (optional: dict mapping petrol, diesel, cng, electric to fractions)."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "daily_trips": {"type": "number"},
                                    "avg_trip_length_km": {"type": "number"},
                                    "mode_share": {"type": "object"},
                                    "fuel_mix": {"type": "object"}
                                },
                                "required": ["name"]
                            }
                        },
                        "emission_standard": {
                            "type": "string",
                            "enum": ["arai_bs6", "arai_bs4", "eea_euro6"],
                            "description": "Emission standards standard profile. Default is 'arai_bs6' (Indian BS-VI)."
                        },
                        "wind_speed_m_s": {
                            "type": "number",
                            "description": "Average wind speed (m/s) for the Gifford-Hanna box model. Default: 3.0"
                        },
                        "mixing_height_m": {
                            "type": "number",
                            "description": "Atmospheric mixing height (meters) for the box model. Default: 500.0"
                        },
                        "study_area_width_m": {
                            "type": "number",
                            "description": "Width (meters) of the study corridor transverse to wind direction. Default: 2000.0"
                        }
                    },
                    "required": ["scenarios"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "estimate_scenario_emissions":
            return await self._estimate_scenario_emissions(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _estimate_scenario_emissions(self, args: dict) -> dict:
        scenarios_input = args.get("scenarios", [])
        std_name = args.get("emission_standard", "arai_bs6")
        u = float(args.get("wind_speed_m_s", 3.0))
        H = float(args.get("mixing_height_m", 500.0))
        W = float(args.get("study_area_width_m", 2000.0))

        if not scenarios_input:
            return {"error": "At least one scenario name is required."}

        factors = self.EMISSION_FACTORS.get(std_name, self.EMISSION_FACTORS["arai_bs6"])

        results = []
        for sc in scenarios_input:
            name = sc.get("name", "Unknown")
            
            # Match template or fallback
            template_key = "baseline"
            for k in ("compact", "transit", "green"):
                if k in name.lower():
                    template_key = k
                    break
            
            tmpl = self.SCENARIO_TEMPLATES[template_key]
            
            trips = float(sc.get("daily_trips") or tmpl["daily_trips"])
            length = float(sc.get("avg_trip_length_km") or tmpl["avg_trip_length_km"])
            m_share = sc.get("mode_share") or tmpl["mode_share"]
            f_mix = sc.get("fuel_mix") or tmpl["fuel_mix"]

            # Calculate VKT (Vehicle Kilometers Traveled) per mode
            # Standardize keys in mode_share
            total_co2 = 0.0
            total_nox = 0.0
            total_pm = 0.0
            total_co = 0.0
            total_vkt = 0.0

            for mode, share in m_share.items():
                mode_vkt = trips * float(share) * length
                # Active travel has zero emissions
                if mode in ("walk_cycle", "active", "walk", "cycle"):
                    continue

                # Find factor category
                cat = "car"
                if "two_wheeler" in mode or "motorcycle" in mode or "scooter" in mode:
                    cat = "two_wheeler"
                elif "rickshaw" in mode or "auto" in mode or "three_wheeler" in mode:
                    cat = "auto_rickshaw"
                elif "bus" in mode or "transit" in mode:
                    cat = "bus"

                # Convert person trips to vehicle trips using standard occupancies
                divisor = 1.0
                if cat == "bus":
                    divisor = 40.0
                elif cat == "auto_rickshaw":
                    divisor = 2.0
                elif cat == "car":
                    divisor = 1.5
                elif cat == "two_wheeler":
                    divisor = 1.1

                mode_vkt /= divisor
                total_vkt += mode_vkt

                cat_factors = factors.get(cat, factors["car"])

                # Distribute VKT across fuel mix
                for fuel, fuel_fraction in f_mix.items():
                    fuel_vkt = mode_vkt * float(fuel_fraction)
                    
                    # For two-wheeler, bus, auto-rickshaw, map to available fuel factors
                    target_fuel = fuel
                    if fuel not in cat_factors:
                        # Fallback for category limits
                        if fuel == "petrol" and "cng" in cat_factors:
                            target_fuel = "cng"
                        elif fuel == "diesel" and "cng" in cat_factors:
                            target_fuel = "cng"
                        else:
                            # Pick first available fuel
                            target_fuel = list(cat_factors.keys())[0]

                    ef = cat_factors.get(target_fuel, {"co2": 0.0, "nox": 0.0, "pm": 0.0, "co": 0.0})

                    total_co2 += fuel_vkt * ef["co2"]
                    total_nox += fuel_vkt * ef["nox"]
                    total_pm += fuel_vkt * ef["pm"]
                    total_co += fuel_vkt * ef["co"]

            # Gifford-Hanna Box Model Equation:
            # delta_C (ug/m3) = Q / (W * u * H)
            # Q is the PM emission rate in micrograms per second (ug/s)
            # total_pm is in grams per day
            daily_sec = 24.0 * 3600.0
            Q_ug_s = (total_pm * 1_000_000.0) / daily_sec
            delta_pm25 = Q_ug_s / (W * u * H)

            results.append({
                "name": name,
                "daily_vkt": total_vkt,
                "co2_kg": total_co2 / 1000.0,
                "nox_kg": total_nox / 1000.0,
                "pm25_kg": total_pm / 1000.0,
                "co_kg": total_co / 1000.0,
                "delta_pm25_ug_m3": delta_pm25
            })

        # Generate comparative markdown report
        std_labels = {"arai_bs6": "Indian BS-VI (ARAI)", "arai_bs4": "Indian BS-IV (ARAI)", "eea_euro6": "European Euro-6 (EEA)"}
        report_sections = [
            f"# Scenario Emissions & Air Quality Impact Report\n",
            f"* **Vehicular Emission Standard**: {std_labels.get(std_name, std_name)}",
            f"* **Meteorology Box Model parameters**: Wind Speed = {u} m/s | Mixing Height = {H} m | Corridor Width = {W} m\n",
            "## Scenario Tailpipe Emissions Comparison (Daily)",
            "| Scenario | Daily Vehicle-km (VKT) | CO₂ Emissions (kg/day) | NOx (kg/day) | PM₂.₅ (kg/day) | Ambient PM₂.₅ Increment |",
            "| :--- | :---: | :---: | :---: | :---: | :---: |"
        ]

        for r in results:
            report_sections.append(
                f"| {r['name']} | {r['daily_vkt']:,.0f} | {r['co2_kg']:,.1f} | {r['nox_kg']:.3f} | {r['pm25_kg']:.4f} | **{r['delta_pm25_ug_m3']:.3f} μg/m³** |"
            )

        report_sections.extend([
            "\n## Methodology & Model Parameters",
            "1. **Tailpipe Emissions**: Computed using distance-based emission factors (g/km) per vehicle mode and fuel class.",
            "2. **Gifford-Hanna Box Model**: Estimates local particulate accumulation over a corridor transverse to wind direction: "
            "$$\\Delta C = \\frac{Q}{W \\cdot u \\cdot H}$$ "
            "where $Q$ is the continuous PM2.5 line source strength (converted to $\\mu$g/s)."
        ])

        report_markdown = "\n".join(report_sections)

        return {
            "status": "success",
            "emission_standard": std_name,
            "scenarios_calculated": len(results),
            "results": results,
            "report_markdown": report_markdown
        }
