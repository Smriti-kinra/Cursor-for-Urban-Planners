from __future__ import annotations
import csv
import io
import json
import math
from pathlib import Path

import httpx
from llm.base import ToolDeclaration
from mcp_servers.demographics_server import DemographicsServer


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class ODServer:
    description = "Origin-Destination Matrix Importer & Desire Line Visualizer"
    tool_names = {"import_od_matrix", "visualize_od_flows", "generate_gravity_od_matrix", "calculate_mode_choice"}

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
            ),
            ToolDeclaration(
                name="generate_gravity_od_matrix",
                description=(
                    "Generate a synthetic Origin-Destination (OD) matrix using a Doubly-Constrained Gravity Model "
                    "over Traffic Analysis Zones (TAZ polygons). Automatically generates trips from resident population "
                    "and employment locations (using custom fields or demographics/employment server estimation fallback), "
                    "applies exponential or power friction decay, and balances row/column targets using Furness/IPFP."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "Optional: GeoJSON FeatureCollection of zones (polygons)."
                        },
                        "geojson_path": {
                            "type": "string",
                            "description": "Optional: Absolute path to TAZ polygons GeoJSON file in the workspace."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "production_rate": {
                            "type": "number",
                            "description": "Daily trips generated per resident (Stage 1 production rate). E.g. 1.2."
                        },
                        "attraction_rate": {
                            "type": "number",
                            "description": "Daily trips generated per workplace job (Stage 1 attraction rate). E.g. 1.5."
                        },
                        "decay_function": {
                            "type": "string",
                            "enum": ["exponential", "power"],
                            "description": "Friction decay function formula. Select 'exponential' or 'power'."
                        },
                        "beta": {
                            "type": "number",
                            "description": "Decay factor for exponential model: e^(-beta * distance). Default: 0.1"
                        },
                        "gamma": {
                            "type": "number",
                            "description": "Decay factor for power model: distance^(-gamma). Default: 2.0"
                        },
                        "population_field": {
                            "type": "string",
                            "description": "Optional: Polygon property field containing resident population."
                        },
                        "jobs_field": {
                            "type": "string",
                            "description": "Optional: Polygon property field containing employment/jobs."
                        },
                        "id_field": {
                            "type": "string",
                            "description": "Optional: Polygon property field for TAZ identifier (e.g. 'id' or 'zone_name')."
                        }
                    },
                    "required": ["workspace", "production_rate", "attraction_rate", "decay_function"]
                }
            ),
            ToolDeclaration(
                name="calculate_mode_choice",
                description=(
                    "Split Origin-Destination (OD) trips across travel modes (Car, Two-Wheeler, Public Transit, Active Travel) "
                    "using a Multinomial Logit (MNL) utility model. Automatically estimates modal times and costs, "
                    "calculates probabilities based on time/cost sensitivity, saves mode-by-mode splits, "
                    "and optionally exports a chosen mode to the main od_matrix.json."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "od_matrix_path": {
                            "type": "string",
                            "description": "Optional: Path to the input od_matrix.json. Defaults to workspace/od_matrix.json."
                        },
                        "beta_time": {
                            "type": "number",
                            "description": "Logit travel time coefficient (per minute). Typically negative. Default: -0.05"
                        },
                        "beta_cost": {
                            "type": "number",
                            "description": "Logit travel cost coefficient (per unit). Typically negative. Default: -0.08"
                        },
                        "car_speed_kmh": {
                            "type": "number",
                            "description": "Average speed for private passenger cars (km/h). Default: 30.0"
                        },
                        "two_wheeler_speed_kmh": {
                            "type": "number",
                            "description": "Average speed for two-wheelers/motorcycles (km/h). Default: 25.0"
                        },
                        "transit_speed_kmh": {
                            "type": "number",
                            "description": "Average operating speed for transit buses (km/h). Default: 18.0"
                        },
                        "active_speed_kmh": {
                            "type": "number",
                            "description": "Average speed for active travel (walking/cycling) (km/h). Default: 5.0"
                        },
                        "car_cost_per_km": {
                            "type": "number",
                            "description": "Per-kilometer cost for driving a passenger car. Default: 12.0"
                        },
                        "two_wheeler_cost_per_km": {
                            "type": "number",
                            "description": "Per-kilometer cost for driving a two-wheeler. Default: 3.0"
                        },
                        "transit_fare_base": {
                            "type": "number",
                            "description": "Base boarding fare for public transit. Default: 10.0"
                        },
                        "transit_fare_per_km": {
                            "type": "number",
                            "description": "Per-kilometer distance fare for public transit. Default: 1.0"
                        },
                        "transit_wait_time_mins": {
                            "type": "number",
                            "description": "Average transit access + waiting time (minutes). Default: 8.0"
                        },
                        "asc_car": {
                            "type": "number",
                            "description": "Alternative Specific Constant for passenger cars. Default: 0.0"
                        },
                        "asc_two_wheeler": {
                            "type": "number",
                            "description": "Alternative Specific Constant for two-wheelers. Default: -0.2"
                        },
                        "asc_transit": {
                            "type": "number",
                            "description": "Alternative Specific Constant for public transit. Default: -0.3"
                        },
                        "asc_active": {
                            "type": "number",
                            "description": "Alternative Specific Constant for active travel. Default: -1.5"
                        },
                        "export_mode": {
                            "type": "string",
                            "enum": ["car", "two_wheeler", "transit", "active"],
                            "description": "Optional: Write this specific mode's flows back to the primary od_matrix.json."
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
        if tool_name == "generate_gravity_od_matrix":
            return await self._generate_gravity_od_matrix(args)
        if tool_name == "calculate_mode_choice":
            return await self._calculate_mode_choice(args)
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

    async def _generate_gravity_od_matrix(self, args: dict) -> dict:
        geojson = args.get("geojson")
        geojson_path = args.get("geojson_path", "").strip()
        workspace = args.get("workspace", "").strip()
        prod_rate = float(args["production_rate"])
        attr_rate = float(args["attraction_rate"])
        decay_type = args["decay_function"].lower()
        beta = float(args.get("beta", 0.1))
        gamma = float(args.get("gamma", 2.0))
        pop_field = args.get("population_field")
        jobs_field = args.get("jobs_field")
        id_field = args.get("id_field")
        ws = args.get("_ws")

        if geojson_path:
            try:
                with open(geojson_path) as f:
                    geojson = json.load(f)
            except Exception as e:
                return {"error": f"Failed to load GeoJSON from path '{geojson_path}': {str(e)}"}

        if not geojson:
            return {"error": "Either 'geojson' or 'geojson_path' must be provided."}
        if not workspace:
            return {"error": "workspace is required to save the generated OD matrix"}

        ws_path = Path(workspace)

        # Parse zones
        features = []
        if geojson.get("type") == "FeatureCollection":
            features = geojson.get("features", [])
        elif geojson.get("type") == "Feature":
            features = [geojson]
        else:
            features = [{"type": "Feature", "geometry": geojson, "properties": {}}]

        if not features:
            return {"error": "GeoJSON contains no valid features."}

        # Setup demographics server in case fallbacks are needed
        demog = DemographicsServer()

        # Step 1: Process TAZs and estimate Productions and Attractions
        zones = []
        for idx, feat in enumerate(features):
            geom = feat.get("geometry")
            if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            
            props = feat.get("properties") or {}
            
            # Resolve zone ID
            zone_id = None
            if id_field and id_field in props:
                zone_id = str(props[id_field])
            else:
                for k in ("zone_name", "zone_id", "id", "name", "OBJECTID"):
                    if k in props:
                        zone_id = str(props[k])
                        break
            if not zone_id:
                zone_id = f"TAZ_{idx+1}"

            # Calculate Centroid
            coords_list = []
            if geom["type"] == "Polygon":
                coords_list = geom["coordinates"]
            else:
                for poly in geom["coordinates"]:
                    coords_list.extend(poly)
            
            flat_pts = []
            for ring in coords_list:
                for pt in ring:
                    flat_pts.append(pt)
            if not flat_pts:
                continue
            lngs = [pt[0] for pt in flat_pts]
            lats = [pt[1] for pt in flat_pts]
            c_lng = sum(lngs) / len(lngs)
            c_lat = sum(lats) / len(lats)

            # Approximate area and radius in meters
            min_lng, max_lng = min(lngs), max(lngs)
            min_lat, max_lat = min(lats), max(lats)
            lat_mid = (min_lat + max_lat) / 2
            dy = (max_lat - min_lat) * 111000
            dx = (max_lng - min_lng) * 111000 * math.cos(math.radians(lat_mid))
            area_m2 = dy * dx * 0.7  # scaled
            radius_m = max(200, int(math.sqrt(area_m2 / math.pi)))

            # Read or estimate population
            population = None
            if pop_field and pop_field in props:
                try:
                    population = float(props[pop_field])
                except (ValueError, TypeError):
                    pass
            if population is None:
                for k in ("population", "pop", "totpop", "resident"):
                    if k in props:
                        try:
                            population = float(props[k])
                            break
                        except (ValueError, TypeError):
                            pass
            if population is None:
                try:
                    demog_res = await demog.execute("get_demographics", {
                        "lat": c_lat,
                        "lng": c_lng,
                        "radius_meters": radius_m
                    })
                    population = float(demog_res.get("population") or 0)
                except Exception:
                    population = 0.0

            # Read or estimate jobs
            jobs = None
            if jobs_field and jobs_field in props:
                try:
                    jobs = float(props[jobs_field])
                except (ValueError, TypeError):
                    pass
            if jobs is None:
                for k in ("jobs", "employment", "workers", "emp"):
                    if k in props:
                        try:
                            jobs = float(props[k])
                            break
                        except (ValueError, TypeError):
                            pass
            if jobs is None:
                try:
                    emp_res = await demog.execute("get_employment_density", {
                        "lat": c_lat,
                        "lng": c_lng,
                        "radius_meters": radius_m,
                        "workspace": workspace
                    })
                    jobs = float(emp_res.get("total_jobs") or 0)
                except Exception:
                    jobs = 0.0

            # Productions and attractions
            prod = population * prod_rate
            attr = jobs * attr_rate

            zones.append({
                "id": zone_id,
                "lat": c_lat,
                "lng": c_lng,
                "population": population,
                "jobs": jobs,
                "productions": prod,
                "attractions": attr
            })

        n_zones = len(zones)
        if n_zones < 2:
            return {"error": "At least 2 zones (polygons) are required to distribute trips."}

        # Initialize distance and initial friction matrix
        T = [[0.0] * n_zones for _ in range(n_zones)]
        dist = [[0.0] * n_zones for _ in range(n_zones)]

        # Scale attractions to match total productions to ensure IPFP converges
        sum_P = sum(z["productions"] for z in zones)
        sum_A = sum(z["attractions"] for z in zones)
        if sum_A > 0 and sum_P > 0:
            scale_factor = sum_P / sum_A
            for z in zones:
                z["attractions"] *= scale_factor

        for i in range(n_zones):
            for j in range(n_zones):
                d_m = _haversine_m(zones[i]["lng"], zones[i]["lat"], zones[j]["lng"], zones[j]["lat"])
                d_km = max(0.1, d_m / 1000.0) # avoid division by zero
                dist[i][j] = d_km

                if decay_type == "exponential":
                    f_ij = math.exp(-beta * d_km)
                else:
                    f_ij = d_km ** (-gamma)
                
                T[i][j] = zones[i]["productions"] * zones[j]["attractions"] * f_ij

        P = [z["productions"] for z in zones]
        A = [z["attractions"] for z in zones]

        # Double constraints: Iterative Proportional Fitting Procedure (IPFP / Furness)
        for iteration in range(20):
            # Row Balancing (Productions)
            for i in range(n_zones):
                row_sum = sum(T[i])
                if row_sum > 0:
                    scale = P[i] / row_sum
                    for j in range(n_zones):
                        T[i][j] *= scale

            # Column Balancing (Attractions)
            for j in range(n_zones):
                col_sum = sum(T[i][j] for i in range(n_zones))
                if col_sum > 0:
                    scale = A[j] / col_sum
                    for i in range(n_zones):
                        T[i][j] *= scale

            # Convergence check
            max_error = 0.0
            for i in range(n_zones):
                row_err = abs(sum(T[i]) - P[i])
                if P[i] > 0:
                    max_error = max(max_error, row_err / P[i])
            for j in range(n_zones):
                col_err = abs(sum(T[i][j] for i in range(n_zones)) - A[j])
                if A[j] > 0:
                    max_error = max(max_error, col_err / A[j])
            
            if max_error < 0.01:
                break

        # Flatten matrix
        od_records = []
        for i in range(n_zones):
            for j in range(n_zones):
                trips = T[i][j]
                if trips >= 0.1:
                    od_records.append({
                        "origin_id": zones[i]["id"],
                        "origin": [zones[i]["lng"], zones[i]["lat"]],
                        "dest_id": zones[j]["id"],
                        "dest": [zones[j]["lng"], zones[j]["lat"]],
                        "trips": round(trips, 1),
                        "label": f"{zones[i]['id']} -> {zones[j]['id']}",
                        "dist_km": round(dist[i][j], 2)
                    })

        # Save to workspace
        od_path = ws_path / "od_matrix.json"
        with open(od_path, "w") as f:
            json.dump(od_records, f, indent=2)

        # Generate report
        report_sections = [
            f"# Travel Demand Model: Gravity Trip Distribution\n",
            f"* **Solver Type**: Doubly-Constrained Gravity Model (Furness IPFP)",
            f"* **Decay function**: {decay_type.upper()} decay model",
            f"* **Decay coefficient**: {'beta = ' + str(beta) if decay_type == 'exponential' else 'gamma = ' + str(gamma)}",
            f"* **Total Zones Evaluated**: {n_zones}",
            f"* **Total Generated Trips**: **{sum(P):,.0f} trips/day**\n"
        ]

        report_sections.extend([
            "## Traffic Analysis Zones (TAZ) Summary",
            "| Zone ID | Centroid Coordinate | Population | Jobs | Productions (P_i) | Attractions (A_j) |",
            "| :--- | :---: | :---: | :---: | :---: | :---: |"
        ])
        for z in zones:
            report_sections.append(
                f"| {z['id']} | {z['lat']:.4f}, {z['lng']:.4f} | {z['population']:,.0f} | {z['jobs']:,.0f} | {z['productions']:,.0f} | {z['attractions']:,.0f} |"
            )

        sorted_flows = sorted(od_records, key=lambda x: x["trips"], reverse=True)
        top_flows = sorted_flows[:10]

        report_sections.extend([
            "\n## Top 10 Distributed Flows",
            "| Rank | Origin Zone | Destination Zone | Geodesic Distance | Daily Trips (balanced) |",
            "| :---: | :--- | :--- | :---: | :---: |"
        ])
        for rank, flow in enumerate(top_flows):
            report_sections.append(
                f"| {rank + 1} | {flow['origin_id']} | {flow['dest_id']} | {flow['dist_km']:.2f} km | **{flow['trips']:,}** |"
            )

        report_markdown = "\n".join(report_sections)

        return {
            "status": "success",
            "zones_count": n_zones,
            "total_trips": round(sum(P)),
            "saved_to": str(od_path),
            "report_markdown": report_markdown,
            "note": "The balanced flows have been written to od_matrix.json. Use visualize_od_flows to render desire lines."
        }

    async def _calculate_mode_choice(self, args: dict) -> dict:
        workspace = args.get("workspace", "").strip()
        input_path = args.get("od_matrix_path", "").strip()
        beta_time = float(args.get("beta_time", -0.05))
        beta_cost = float(args.get("beta_cost", -0.08))
        
        car_speed = float(args.get("car_speed_kmh", 30.0))
        tw_speed = float(args.get("two_wheeler_speed_kmh", 25.0))
        transit_speed = float(args.get("transit_speed_kmh", 18.0))
        active_speed = float(args.get("active_speed_kmh", 5.0))
        
        car_cost = float(args.get("car_cost_per_km", 12.0))
        tw_cost = float(args.get("two_wheeler_cost_per_km", 3.0))
        transit_fare_base = float(args.get("transit_fare_base", 10.0))
        transit_fare_per_km = float(args.get("transit_fare_per_km", 1.0))
        transit_wait = float(args.get("transit_wait_time_mins", 8.0))
        
        asc_car = float(args.get("asc_car", 0.0))
        asc_tw = float(args.get("asc_two_wheeler", -0.2))
        asc_transit = float(args.get("asc_transit", -0.3))
        asc_active = float(args.get("asc_active", -1.5))
        
        export_mode = args.get("export_mode")

        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        if not input_path:
            input_path = ws_path / "od_matrix.json"
        else:
            input_path = Path(input_path)

        if not input_path.exists():
            return {"error": f"Input OD matrix not found at '{input_path}'. Run generate_gravity_od_matrix or import_od_matrix first."}

        with open(input_path) as f:
            od_records = json.load(f)

        if not od_records:
            return {"error": "Input OD matrix is empty."}

        split_records = []
        totals = {"car": 0.0, "two_wheeler": 0.0, "transit": 0.0, "active": 0.0, "total": 0.0}

        for r in od_records:
            dist_km = float(r.get("dist_km", 1.0))
            total_trips = float(r.get("trips", 1.0))
            
            # 1. Travel Times (minutes)
            t_car = (dist_km / car_speed) * 60.0
            t_tw = (dist_km / tw_speed) * 60.0
            t_transit = (dist_km / transit_speed) * 60.0 + transit_wait
            t_active = (dist_km / active_speed) * 60.0
            
            # 2. Travel Costs
            c_car = dist_km * car_cost
            c_tw = dist_km * tw_cost
            c_transit = transit_fare_base + dist_km * transit_fare_per_km
            c_active = 0.0
            
            # 3. Utilities
            u_car = asc_car + beta_time * t_car + beta_cost * c_car
            u_tw = asc_tw + beta_time * t_tw + beta_cost * c_tw
            u_transit = asc_transit + beta_time * t_transit + beta_cost * c_transit
            u_active = asc_active + beta_time * t_active + beta_cost * c_active
            
            # 4. MNL Probabilities
            exp_car = math.exp(max(-50, min(50, u_car)))
            exp_tw = math.exp(max(-50, min(50, u_tw)))
            exp_transit = math.exp(max(-50, min(50, u_transit)))
            exp_active = math.exp(max(-50, min(50, u_active)))
            
            sum_exp = exp_car + exp_tw + exp_transit + exp_active
            
            p_car = exp_car / sum_exp
            p_tw = exp_tw / sum_exp
            p_transit = exp_transit / sum_exp
            p_active = exp_active / sum_exp
            
            # 5. Distribute trips
            trips_car = total_trips * p_car
            trips_tw = total_trips * p_tw
            trips_transit = total_trips * p_transit
            trips_active = total_trips * p_active
            
            totals["car"] += trips_car
            totals["two_wheeler"] += trips_tw
            totals["transit"] += trips_transit
            totals["active"] += trips_active
            totals["total"] += total_trips
            
            split_records.append({
                "origin_id": r.get("origin_id", "Unknown"),
                "dest_id": r.get("dest_id", "Unknown"),
                "origin": r["origin"],
                "dest": r["dest"],
                "total_trips": total_trips,
                "trips_car": round(trips_car, 1),
                "trips_two_wheeler": round(trips_tw, 1),
                "trips_transit": round(trips_transit, 1),
                "trips_active": round(trips_active, 1),
                "dist_km": round(dist_km, 2),
                "label": r.get("label", "")
            })

        # Save detailed mode split file
        split_path = ws_path / "od_matrix_mode_split.json"
        with open(split_path, "w") as f:
            json.dump(split_records, f, indent=2)

        # Handle export_mode if specified
        exported_path = None
        if export_mode in ("car", "two_wheeler", "transit", "active"):
            field = f"trips_{export_mode}"
            exported_od = []
            for sr in split_records:
                exported_od.append({
                    "origin_id": sr["origin_id"],
                    "dest_id": sr["dest_id"],
                    "origin": sr["origin"],
                    "dest": sr["dest"],
                    "trips": sr[field],
                    "label": f"{sr['origin_id']} -> {sr['dest_id']} ({export_mode})",
                    "dist_km": sr["dist_km"]
                })
            exported_path = ws_path / "od_matrix.json"
            with open(exported_path, "w") as f:
                json.dump(exported_od, f, indent=2)

        # Generate report
        tot = totals["total"] if totals["total"] > 0 else 1.0
        report_sections = [
            f"# Mode Choice Solver Report (Multinomial Logit Model)\n",
            f"* **Input OD Matrix**: {input_path.name}",
            f"* **Logit Sensitivity**: $\\beta_{{time}}$ = {beta_time} | $\\beta_{{cost}}$ = {beta_cost}",
            f"* **Alternative Specific Constants (ASCs)**: Car = {asc_car} | 2-Wheeler = {asc_tw} | Public Transit = {asc_transit} | Active = {asc_active}\n",
            "## Travel Commute Modal Split Summary",
            "| Travel Mode | Total Trips/Day | Split Percentage | Base Speed | Per-Km Cost |",
            "| :--- | :---: | :---: | :---: | :---: |"
        ]
        
        report_sections.append(f"| 🚗 **Passenger Car** | {totals['car']:,.0f} | {totals['car']/tot * 100:.1f}% | {car_speed} km/h | {car_cost} INR/km |")
        report_sections.append(f"| 🛵 **Two-Wheeler** | {totals['two_wheeler']:,.0f} | {totals['two_wheeler']/tot * 100:.1f}% | {tw_speed} km/h | {tw_cost} INR/km |")
        report_sections.append(f"| 🚌 **Public Transit** | {totals['transit']:,.0f} | {totals['transit']/tot * 100:.1f}% | {transit_speed} km/h | {transit_fare_base} + {transit_fare_per_km}/km |")
        report_sections.append(f"| 🚶 **Active Travel** | {totals['active']:,.0f} | {totals['active']/tot * 100:.1f}% | {active_speed} km/h | Free |")
        report_sections.append(f"| **Total Commute Demand** | **{totals['total']:,.0f}** | **100%** | - | - |")

        if exported_path:
            report_sections.append(f"\n> 📢 **Export Active**: Exported '{export_mode}' flows directly to `od_matrix.json` for mapping or routing assignment.")

        report_markdown = "\n".join(report_sections)

        return {
            "status": "success",
            "total_trips": round(totals["total"]),
            "mode_splits": {m: round(totals[m]) for m in ("car", "two_wheeler", "transit", "active")},
            "saved_mode_split_matrix": str(split_path),
            "exported_primary_matrix": str(exported_path) if exported_path else None,
            "report_markdown": report_markdown
        }
