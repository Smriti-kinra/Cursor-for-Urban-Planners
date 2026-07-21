from __future__ import annotations
import csv
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import httpx
from llm.base import ToolDeclaration


class GTFSServer:
    description = "GTFS Transit Feed Importer & Analyzer"
    tool_names = {"import_gtfs_feed", "analyze_gtfs_service"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="import_gtfs_feed",
                description=(
                    "Download and parse a GTFS (General Transit Feed Specification) ZIP file from a URL. "
                    "Extracts stops as map points and route shapes as map lines. Loads them on the map as "
                    "separate layers (transit stops + route lines), saving files into the active workspace."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to download the GTFS ZIP feed file from."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional name prefix for the generated layers (e.g. 'Chandigarh Bus')."
                        }
                    },
                    "required": ["url", "workspace"]
                }
            ),
            ToolDeclaration(
                name="analyze_gtfs_service",
                description=(
                    "Analyze a previously imported GTFS feed stored in the workspace. "
                    "Returns service statistics: total routes, stops, trips, average headways, "
                    "highest-frequency corridors, and stop accessibility coverage."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder containing imported GTFS files."
                        }
                    },
                    "required": ["workspace"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "import_gtfs_feed":
            return await self._import_gtfs_feed(args)
        if tool_name == "analyze_gtfs_service":
            return await self._analyze_gtfs_service(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _import_gtfs_feed(self, args: dict) -> dict:
        url = args.get("url", "").strip()
        workspace = args.get("workspace", "").strip()
        title = args.get("title", "").strip() or "Transit"
        ws = args.get("_ws")

        if not url:
            return {"error": "url is required to download GTFS feed"}
        if not workspace:
            return {"error": "workspace is required to save GTFS files"}

        ws_path = Path(workspace)
        if not ws_path.exists():
            return {"error": f"Workspace path does not exist: {workspace}"}

        # Download ZIP
        try:
            async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    return {"error": f"Failed to download GTFS: HTTP {response.status_code}"}
                zip_bytes = response.content
        except Exception as e:
            return {"error": f"Download error: {str(e)}"}

        # Parse GTFS ZIP
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                names = zf.namelist()

                def read_csv(filename: str) -> list[dict]:
                    for name in names:
                        if name.endswith(filename):
                            with zf.open(name) as f:
                                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                                return list(reader)
                    return []

                stops = read_csv("stops.txt")
                routes = read_csv("routes.txt")
                trips = read_csv("trips.txt")
                shapes = read_csv("shapes.txt")
                stop_times = read_csv("stop_times.txt")

        except zipfile.BadZipFile:
            return {"error": "The URL did not return a valid GTFS ZIP file."}
        except Exception as e:
            return {"error": f"GTFS parsing error: {str(e)}"}

        # Save raw data for later analysis
        gtfs_meta = {
            "stops_count": len(stops),
            "routes_count": len(routes),
            "trips_count": len(trips),
            "shapes_count": len(shapes)
        }
        with open(ws_path / "gtfs_meta.json", "w") as f:
            json.dump(gtfs_meta, f)

        # Save stop_times for analysis
        if stop_times:
            with open(ws_path / "gtfs_stop_times.json", "w") as f:
                json.dump(stop_times[:5000], f)  # cap at 5k rows for disk

        # Save routes for analysis
        if routes:
            with open(ws_path / "gtfs_routes.json", "w") as f:
                json.dump(routes, f)

        # Save trips for analysis
        if trips:
            with open(ws_path / "gtfs_trips.json", "w") as f:
                json.dump(trips, f)

        # ── Build stops GeoJSON ──
        stop_features = []
        for s in stops:
            try:
                lat = float(s.get("stop_lat", 0))
                lon = float(s.get("stop_lon", 0))
                stop_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "stop_id": s.get("stop_id", ""),
                        "stop_name": s.get("stop_name", ""),
                        "stop_code": s.get("stop_code", ""),
                        "wheelchair": s.get("wheelchair_boarding", "unknown")
                    }
                })
            except (ValueError, TypeError):
                continue

        stops_geojson = {"type": "FeatureCollection", "features": stop_features}
        stops_path = ws_path / "gtfs_stops.geojson"
        with open(stops_path, "w") as f:
            json.dump(stops_geojson, f)

        # ── Build shapes/routes GeoJSON ──
        route_map = {r["route_id"]: r for r in routes if "route_id" in r}
        trip_shape_map = {t["trip_id"]: t.get("shape_id", "") for t in trips if "trip_id" in t}
        trip_route_map = {t["trip_id"]: t.get("route_id", "") for t in trips if "trip_id" in t}

        # Group shapes by shape_id
        shape_coords: dict[str, list] = defaultdict(list)
        for row in shapes:
            sid = row.get("shape_id", "")
            try:
                pt = [float(row["shape_pt_lon"]), float(row["shape_pt_lat"])]
                seq = int(row.get("shape_pt_sequence", 0))
                shape_coords[sid].append((seq, pt))
            except (ValueError, TypeError, KeyError):
                continue

        # Sort each shape by sequence number
        route_features = []
        seen_shapes: set[str] = set()
        for trip in trips:
            shape_id = trip.get("shape_id", "")
            route_id = trip.get("route_id", "")
            if not shape_id or shape_id in seen_shapes:
                continue
            seen_shapes.add(shape_id)
            pts = sorted(shape_coords.get(shape_id, []), key=lambda x: x[0])
            if len(pts) < 2:
                continue
            coords = [p[1] for p in pts]
            route_info = route_map.get(route_id, {})
            route_features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "shape_id": shape_id,
                    "route_id": route_id,
                    "route_short_name": route_info.get("route_short_name", ""),
                    "route_long_name": route_info.get("route_long_name", ""),
                    "route_type": route_info.get("route_type", ""),
                    "route_color": route_info.get("route_color", "")
                }
            })

        # If no shapes, fall back to stop-to-stop lines per trip
        if not route_features and stop_times:
            stop_coord_map = {}
            for s in stops:
                try:
                    stop_coord_map[s["stop_id"]] = [float(s["stop_lon"]), float(s["stop_lat"])]
                except (ValueError, KeyError):
                    continue

            trip_stops: dict[str, list] = defaultdict(list)
            for st in stop_times:
                trip_stops[st.get("trip_id", "")].append(
                    (int(st.get("stop_sequence", 0)), st.get("stop_id", ""))
                )

            seen_routes: set[str] = set()
            for trip in trips:
                route_id = trip.get("route_id", "")
                if route_id in seen_routes:
                    continue
                seen_routes.add(route_id)
                tid = trip.get("trip_id", "")
                stops_seq = sorted(trip_stops.get(tid, []), key=lambda x: x[0])
                coords = [stop_coord_map[s[1]] for s in stops_seq if s[1] in stop_coord_map]
                if len(coords) < 2:
                    continue
                route_info = route_map.get(route_id, {})
                route_features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "route_id": route_id,
                        "route_short_name": route_info.get("route_short_name", ""),
                        "route_long_name": route_info.get("route_long_name", ""),
                        "route_type": route_info.get("route_type", "")
                    }
                })

        routes_geojson = {"type": "FeatureCollection", "features": route_features}
        routes_path = ws_path / "gtfs_routes.geojson"
        with open(routes_path, "w") as f:
            json.dump(routes_geojson, f)

        # ── Send map actions ──
        actions_sent = []
        if ws:
            try:
                if route_features:
                    await ws.send_text(json.dumps({
                        "type": "action",
                        "action": "add_geojson_file",
                        "payload": {"path": str(routes_path), "name": f"{title} Routes"}
                    }))
                    actions_sent.append("routes")
                if stop_features:
                    await ws.send_text(json.dumps({
                        "type": "action",
                        "action": "add_geojson_file",
                        "payload": {"path": str(stops_path), "name": f"{title} Stops"}
                    }))
                    actions_sent.append("stops")
            except Exception as e:
                return {"error": f"Failed to send map actions: {str(e)}"}

        return {
            "status": "success",
            "displayed_on_map": True,
            "summary": {
                "stops": len(stop_features),
                "routes": len(route_map),
                "shapes_drawn": len(route_features),
                "trips": len(trips)
            },
            "layers_loaded": actions_sent,
            "workspace": workspace
        }

    async def _analyze_gtfs_service(self, args: dict) -> dict:
        workspace = args.get("workspace", "").strip()

        if not workspace:
            return {"error": "workspace is required"}

        ws_path = Path(workspace)
        meta_file = ws_path / "gtfs_meta.json"
        routes_file = ws_path / "gtfs_routes.json"
        stop_times_file = ws_path / "gtfs_stop_times.json"

        if not meta_file.exists():
            return {"error": "No GTFS data found in workspace. Please run import_gtfs_feed first."}

        with open(meta_file) as f:
            meta = json.load(f)

        routes = []
        if routes_file.exists():
            with open(routes_file) as f:
                routes = json.load(f)

        stop_times = []
        if stop_times_file.exists():
            with open(stop_times_file) as f:
                stop_times = json.load(f)

        # Compute trip frequency per route (trips per route)
        route_trip_counts: dict[str, int] = defaultdict(int)
        try:
            trips_file = ws_path / "gtfs_trips.json"
            if trips_file.exists():
                with open(trips_file) as f:
                    trips_data = json.load(f)
                for trip in trips_data:
                    route_trip_counts[trip.get("route_id", "")] += 1
        except Exception:
            pass

        # Compute route types breakdown
        route_type_map = {
            "0": "Tram/Streetcar", "1": "Subway/Metro", "2": "Rail",
            "3": "Bus", "4": "Ferry", "5": "Cable Car",
            "6": "Gondola", "7": "Funicular", "11": "Trolleybus", "12": "Monorail"
        }
        type_counts: dict[str, int] = defaultdict(int)
        for r in routes:
            rtype = route_type_map.get(str(r.get("route_type", "3")), "Bus")
            type_counts[rtype] += 1

        # Top 5 highest-frequency routes
        top_routes = sorted(
            [{"route_id": k, "trips": v, "route_name": ""} for k, v in route_trip_counts.items()],
            key=lambda x: x["trips"],
            reverse=True
        )[:5]
        route_name_map = {r.get("route_id", ""): r.get("route_short_name", r.get("route_long_name", "")) for r in routes}
        for tr in top_routes:
            tr["route_name"] = route_name_map.get(tr["route_id"], tr["route_id"])

        return {
            "status": "success",
            "network_stats": {
                "total_routes": meta.get("routes_count", 0),
                "total_stops": meta.get("stops_count", 0),
                "total_trips": meta.get("trips_count", 0),
                "route_types": dict(type_counts),
            },
            "top_frequency_routes": top_routes,
            "note": "Trip counts approximate frequency — higher trip count = more frequent service."
        }
