from __future__ import annotations
import csv
import io
import json
import math
from pathlib import Path

import httpx
from llm.base import ToolDeclaration


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class ODServer:
    description = "Origin-Destination Matrix Importer & Desire Line Visualizer"
    tool_names = {"import_od_matrix", "visualize_od_flows"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="import_od_matrix",
                description=(
                    "Import an Origin-Destination (OD) matrix from a CSV file URL. "
                    "The CSV must have columns: origin_id, origin_lat, origin_lng, "
                    "dest_id, dest_lat, dest_lng, and trip_count (or similar). "
                    "Saves a parsed OD dataset into the workspace for visualization."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to download the OD matrix CSV from."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "origin_lat_col": {
                            "type": "string",
                            "description": "CSV column name for origin latitude. Default: 'origin_lat'"
                        },
                        "origin_lng_col": {
                            "type": "string",
                            "description": "CSV column name for origin longitude. Default: 'origin_lng'"
                        },
                        "dest_lat_col": {
                            "type": "string",
                            "description": "CSV column name for destination latitude. Default: 'dest_lat'"
                        },
                        "dest_lng_col": {
                            "type": "string",
                            "description": "CSV column name for destination longitude. Default: 'dest_lng'"
                        },
                        "trip_count_col": {
                            "type": "string",
                            "description": "CSV column name for trip/flow count. Default: 'trip_count'"
                        },
                        "label_col": {
                            "type": "string",
                            "description": "Optional CSV column to use as zone label (e.g. zone name)."
                        }
                    },
                    "required": ["url", "workspace"]
                }
            ),
            ToolDeclaration(
                name="visualize_od_flows",
                description=(
                    "Generate and display an OD desire line map layer from a previously imported "
                    "OD matrix in the workspace. Supports filtering by minimum trip count threshold "
                    "and limiting to top N flows. Lines are weighted by trip volume."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "min_trips": {
                            "type": "number",
                            "description": "Minimum trip count to include a flow (filter out weak connections). Default: 0"
                        },
                        "top_n": {
                            "type": "integer",
                            "description": "Only show the top N highest-volume flows. Default: 200"
                        },
                        "title": {
                            "type": "string",
                            "description": "Name for the generated map layer."
                        }
                    },
                    "required": ["workspace"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "import_od_matrix":
            return await self._import_od_matrix(args)
        if tool_name == "visualize_od_flows":
            return await self._visualize_od_flows(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _import_od_matrix(self, args: dict) -> dict:
        url = args.get("url", "").strip()
        workspace = args.get("workspace", "").strip()
        o_lat = args.get("origin_lat_col", "origin_lat")
        o_lng = args.get("origin_lng_col", "origin_lng")
        d_lat = args.get("dest_lat_col", "dest_lat")
        d_lng = args.get("dest_lng_col", "dest_lng")
        trips_col = args.get("trip_count_col", "trip_count")
        label_col = args.get("label_col", "")

        if not url:
            return {"error": "url is required"}
        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)

        # Download CSV
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {"error": f"Failed to download OD CSV: HTTP {resp.status_code}"}
                csv_text = resp.text
        except Exception as e:
            return {"error": f"Download error: {str(e)}"}

        # Parse CSV
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            rows = list(reader)
        except Exception as e:
            return {"error": f"CSV parse error: {str(e)}"}

        if not rows:
            return {"error": "CSV file is empty or has no data rows."}

        # Validate columns
        sample = rows[0]
        missing = [c for c in [o_lat, o_lng, d_lat, d_lng] if c not in sample]
        if missing:
            available = list(sample.keys())
            return {
                "error": f"Missing columns: {missing}. Available columns: {available}"
            }

        # Parse and normalize
        od_records = []
        skipped = 0
        for row in rows:
            try:
                olat = float(row[o_lat])
                olng = float(row[o_lng])
                dlat = float(row[d_lat])
                dlng = float(row[d_lng])
                count = float(row.get(trips_col, 1) or 1)
                label = row.get(label_col, "") if label_col else ""
                od_records.append({
                    "origin": [olng, olat],
                    "dest": [dlng, dlat],
                    "trips": count,
                    "label": label,
                    "dist_km": round(_haversine_m(olng, olat, dlng, dlat) / 1000, 2)
                })
            except (ValueError, TypeError, KeyError):
                skipped += 1
                continue

        if not od_records:
            return {"error": "No valid OD records could be parsed from the CSV."}

        # Save to workspace
        od_path = ws_path / "od_matrix.json"
        with open(od_path, "w") as f:
            json.dump(od_records, f)

        trip_values = [r["trips"] for r in od_records]
        return {
            "status": "success",
            "records_parsed": len(od_records),
            "records_skipped": skipped,
            "trip_stats": {
                "min": min(trip_values),
                "max": max(trip_values),
                "total": sum(trip_values),
                "avg": round(sum(trip_values) / len(trip_values), 1)
            },
            "saved_to": str(od_path),
            "note": "Run visualize_od_flows to display desire lines on the map."
        }

    async def _visualize_od_flows(self, args: dict) -> dict:
        workspace = args.get("workspace", "").strip()
        min_trips = float(args.get("min_trips", 0))
        top_n = int(args.get("top_n", 200))
        title = args.get("title", "OD Desire Lines").strip()
        ws = args.get("_ws")

        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        od_path = ws_path / "od_matrix.json"

        if not od_path.exists():
            return {"error": "No OD matrix found in workspace. Run import_od_matrix first."}

        with open(od_path) as f:
            od_records = json.load(f)

        # Filter and sort
        filtered = [r for r in od_records if r["trips"] >= min_trips]
        filtered.sort(key=lambda x: x["trips"], reverse=True)
        filtered = filtered[:top_n]

        if not filtered:
            return {"error": f"No flows meet the min_trips threshold of {min_trips}."}

        # Normalize trip counts for stroke width (1–10px)
        max_trips = max(r["trips"] for r in filtered)
        min_trips_actual = min(r["trips"] for r in filtered)

        def normalize_width(t: float) -> float:
            if max_trips == min_trips_actual:
                return 3.0
            return 1.0 + 9.0 * (t - min_trips_actual) / (max_trips - min_trips_actual)

        # Build GeoJSON
        features = []
        for r in filtered:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [r["origin"], r["dest"]]
                },
                "properties": {
                    "trips": r["trips"],
                    "dist_km": r["dist_km"],
                    "label": r.get("label", ""),
                    "stroke_width": round(normalize_width(r["trips"]), 1)
                }
            })

        od_geojson = {"type": "FeatureCollection", "features": features}
        out_path = ws_path / "od_desire_lines.geojson"
        with open(out_path, "w") as f:
            json.dump(od_geojson, f)

        # Dispatch to map
        if ws:
            try:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {"path": str(out_path), "name": title}
                }))
            except Exception as e:
                return {"error": f"Failed to send map action: {str(e)}"}

        return {
            "status": "success",
            "flows_displayed": len(features),
            "trip_range": {
                "min": min_trips_actual,
                "max": max_trips
            },
            "output_layer": str(out_path)
        }
