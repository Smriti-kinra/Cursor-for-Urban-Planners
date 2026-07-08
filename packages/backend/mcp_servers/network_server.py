from __future__ import annotations
import os
import json
import math
from pathlib import Path
from llm.base import ToolDeclaration

def haversine_distance(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    """Calculate the Haversine distance in meters between two points (lng, lat)."""
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    R = 6371000  # radius of Earth in meters
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def _build_networkx_graph(geojson_data: dict) -> any:
    """Build a networkx MultiGraph from GeoJSON LineStrings."""
    import networkx as nx
    G = nx.MultiGraph()
    
    features = []
    if not geojson_data:
        return G
    if geojson_data.get("type") == "FeatureCollection":
        features = geojson_data.get("features", [])
    elif geojson_data.get("type") == "Feature":
        features = [geojson_data]
    else:
        features = [{"type": "Feature", "geometry": geojson_data, "properties": {}}]
        
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        g_type = geom.get("type")
        props = feat.get("properties") or {}
        
        coords_list = []
        if g_type == "LineString":
            coords_list = [geom.get("coordinates", [])]
        elif g_type == "MultiLineString":
            coords_list = geom.get("coordinates", [])
            
        for coords in coords_list:
            if len(coords) < 2:
                continue
            for idx in range(len(coords) - 1):
                u = tuple(coords[idx])   # (lng, lat)
                v = tuple(coords[idx+1]) # (lng, lat)
                
                length = haversine_distance(u, v)
                G.add_edge(
                    u, v,
                    length=length,
                    highway=props.get("highway", "residential"),
                    name=props.get("name", "unnamed")
                )
    return G

class NetworkServer:
    description = "Street Network Analysis & Shortest Path Routing"
    tool_names = {"analyze_street_network", "find_shortest_path", "route_multi_stop"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="analyze_street_network",
                description=(
                    "Analyze a road network GeoJSON to calculate topological metrics "
                    "(intersection counts, road lengths, intersection density) and identify traffic bottlenecks "
                    "using Betweenness Centrality. Saves results inside the active workspace."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "GeoJSON FeatureCollection containing LineString road/street lines."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional: Title for the map layer (e.g. 'Bottleneck Nodes')."
                        }
                    },
                    "required": ["geojson", "workspace"]
                }
            ),
            ToolDeclaration(
                name="find_shortest_path",
                description=(
                    "Calculate the shortest path routing between two lat/lng coordinates using a road network GeoJSON. "
                    "Saves the routing path as a LineString GeoJSON file in the workspace and displays it on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "GeoJSON FeatureCollection containing LineString road lines."
                        },
                        "start_lat": {"type": "number", "description": "Latitude coordinate of the starting point."},
                        "start_lng": {"type": "number", "description": "Longitude coordinate of the starting point."},
                        "end_lat": {"type": "number", "description": "Latitude coordinate of the ending point."},
                        "end_lng": {"type": "number", "description": "Longitude coordinate of the ending point."},
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional: Title for the map layer (e.g. 'Shortest Route')."
                        }
                    },
                    "required": ["geojson", "start_lat", "start_lng", "end_lat", "end_lng", "workspace"]
                }
            ),
            ToolDeclaration(
                name="route_multi_stop",
                description=(
                    "Generate an explicit multi-stop route along a road network GeoJSON, "
                    "connecting a sequence of waypoints (stops/origins/destinations) in order. "
                    "Uses Dijkstra shortest-path routing between each consecutive pair of stops. "
                    "Returns a single continuous LineString route and per-leg distance/time stats."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "geojson": {
                            "type": "object",
                            "description": "GeoJSON FeatureCollection containing LineString road lines."
                        },
                        "waypoints": {
                            "type": "array",
                            "description": "Ordered list of waypoints to route through. Each waypoint: {lat, lng, label}.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                    "label": {"type": "string"}
                                },
                                "required": ["lat", "lng"]
                            }
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder."
                        },
                        "title": {
                            "type": "string",
                            "description": "Name for the output route layer."
                        }
                    },
                    "required": ["geojson", "waypoints", "workspace"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "analyze_street_network":
            return await self._analyze_street_network(args)
        if tool_name == "find_shortest_path":
            return await self._find_shortest_path(args)
        if tool_name == "route_multi_stop":
            return await self._route_multi_stop(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _analyze_street_network(self, args: dict) -> dict:
        geojson = args.get("geojson")
        workspace = args.get("workspace", "").strip()
        title = args.get("title", "").strip() or "Junction Bottlenecks"
        ws = args.get("_ws")

        if not geojson:
            return {"error": "geojson is required"}
        if not workspace:
            return {"error": "workspace is required to save output layers"}

        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx library is not installed on the system."}

        try:
            G = _build_networkx_graph(geojson)
            if not G.nodes:
                return {"error": "GeoJSON contains no valid LineString coordinates to build a graph."}

            # 1. Compute basic statistics
            total_nodes = len(G.nodes)
            total_edges = len(G.edges)
            
            # Road lengths
            total_len_m = sum(d.get("length", 0) for _, _, d in G.edges(data=True))
            
            # Intersection nodes (nodes with degree > 2)
            intersections = [n for n, deg in G.degree() if deg > 2]
            total_intersections = len(intersections)
            
            # Study area bounding box
            lngs = [n[0] for n in G.nodes]
            lats = [n[1] for n in G.nodes]
            min_lng, max_lng = min(lngs), max(lngs)
            min_lat, max_lat = min(lats), max(lats)
            
            w_m = haversine_distance((min_lng, min_lat), (max_lng, min_lat))
            h_m = haversine_distance((min_lng, min_lat), (min_lng, max_lat))
            area_sq_km = (w_m * h_m) / 1_000_000.0
            
            density = total_intersections / max(0.001, area_sq_km)

            # 2. Compute Traffic Bottlenecks (Betweenness Centrality)
            centrality = nx.betweenness_centrality(G, weight="length")
            sorted_nodes = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
            top_count = max(1, int(len(sorted_nodes) * 0.05))
            top_nodes = sorted_nodes[:top_count]

            # Generate GeoJSON Point layer
            bottleneck_features = []
            for idx, (node, score) in enumerate(top_nodes):
                bottleneck_features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [node[0], node[1]]
                    },
                    "properties": {
                        "id": idx + 1,
                        "centrality_score": round(score, 4),
                        "degree": G.degree(node)
                    }
                })
            
            out_geojson = {
                "type": "FeatureCollection",
                "features": bottleneck_features
            }

            # Save to workspace
            filename = "junction_bottlenecks.geojson"
            target_path = Path(workspace) / filename
            with open(target_path, "w") as f:
                json.dump(out_geojson, f, indent=2)

            # Dispatch action to client
            if ws:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(target_path),
                        "name": title
                    }
                }))

            return {
                "status": "success",
                "summary": {
                    "total_nodes": total_nodes,
                    "total_edges": total_edges,
                    "total_road_length_km": round(total_len_m / 1000.0, 2),
                    "total_intersections": total_intersections,
                    "estimated_area_sq_km": round(area_sq_km, 3),
                    "intersection_density_per_sq_km": round(density, 2),
                    "bottlenecks_count": len(bottleneck_features)
                },
                "output_layer": str(target_path)
            }

        except Exception as e:
            return {"error": f"Topological network analysis failed: {str(e)}"}

    async def _find_shortest_path(self, args: dict) -> dict:
        geojson = args.get("geojson")
        start_lat = float(args.get("start_lat", 0))
        start_lng = float(args.get("start_lng", 0))
        end_lat = float(args.get("end_lat", 0))
        end_lng = float(args.get("end_lng", 0))
        workspace = args.get("workspace", "").strip()
        title = args.get("title", "").strip() or "Shortest Route"
        ws = args.get("_ws")

        if not geojson:
            return {"error": "geojson is required"}
        if not workspace:
            return {"error": "workspace is required to save route outputs"}

        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx library is not installed on the system."}

        try:
            G = _build_networkx_graph(geojson)
            if not G.nodes:
                return {"error": "GeoJSON contains no valid LineString coordinates."}

            # Find closest nodes to start and end points
            start_coord = (start_lng, start_lat)
            end_coord = (end_lng, end_lat)
            
            closest_start = None
            closest_end = None
            min_d_start = float("inf")
            min_d_end = float("inf")
            
            for node in G.nodes:
                d_start = haversine_distance(node, start_coord)
                if d_start < min_d_start:
                    min_d_start = d_start
                    closest_start = node
                    
                d_end = haversine_distance(node, end_coord)
                if d_end < min_d_end:
                    min_d_end = d_end
                    closest_end = node

            if not closest_start or not closest_end:
                return {"error": "Could not identify start or end node projections on the graph."}

            # Execute shortest path
            path = nx.shortest_path(G, source=closest_start, target=closest_end, weight="length")
            path_length = nx.shortest_path_length(G, source=closest_start, target=closest_end, weight="length")

            # Build LineString geometry
            coords = [[n[0], n[1]] for n in path]
            route_geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": {
                        "name": title,
                        "length_meters": round(path_length, 1),
                        "estimated_travel_time_mins": round((path_length / 11.1) / 60.0, 1)  # assuming 40 km/h average
                    }
                }]
            }

            # Save route file to workspace
            filename = "shortest_route.geojson"
            target_path = Path(workspace) / filename
            with open(target_path, "w") as f:
                json.dump(route_geojson, f, indent=2)

            # Dispatch action
            if ws:
                await ws.send_text(json.dumps({
                    "type": "action",
                    "action": "add_geojson_file",
                    "payload": {
                        "path": str(target_path),
                        "name": title
                    }
                }))

            return {
                "status": "success",
                "route_stats": {
                    "total_distance_meters": round(path_length, 1),
                    "estimated_travel_time_mins": round((path_length / 11.1) / 60.0, 1),
                    "closest_start_offset_meters": round(min_d_start, 1),
                    "closest_end_offset_meters": round(min_d_end, 1)
                },
                "output_layer": str(target_path)
            }


        except nx.NetworkXNoPath:
            return {"error": "No topological path exists between the start and end coordinates."}
        except Exception as e:
            return {"error": f"Shortest path calculation failed: {str(e)}"}

    async def _route_multi_stop(self, args: dict) -> dict:
        geojson = args.get("geojson")
        waypoints = args.get("waypoints", [])
        workspace = args.get("workspace", "").strip()
        title = args.get("title", "Multi-Stop Route").strip()
        ws = args.get("_ws")

        if not geojson:
            return {"error": "geojson is required"}
        if len(waypoints) < 2:
            return {"error": "At least 2 waypoints are required for multi-stop routing."}
        if not workspace:
            return {"error": "workspace is required"}

        try:
            import networkx as nx
        except ImportError:
            return {"error": "networkx library is not installed."}

        try:
            G = _build_networkx_graph(geojson)
            if not G.nodes:
                return {"error": "GeoJSON contains no valid LineString coordinates."}

            nodes_list = list(G.nodes)

            def closest_node(lat: float, lng: float) -> tuple:
                coord = (lng, lat)
                best = min(nodes_list, key=lambda n: haversine_distance(n, coord))
                return best

            all_coords = []
            legs = []
            total_dist = 0.0

            for i in range(len(waypoints) - 1):
                wp_a = waypoints[i]
                wp_b = waypoints[i + 1]

                node_a = closest_node(float(wp_a["lat"]), float(wp_a["lng"]))
                node_b = closest_node(float(wp_b["lat"]), float(wp_b["lng"]))

                try:
                    path = nx.shortest_path(G, source=node_a, target=node_b, weight="length")
                    leg_len = nx.shortest_path_length(G, source=node_a, target=node_b, weight="length")
                except nx.NetworkXNoPath:
                    return {"error": f"No path found between waypoint {i+1} and {i+2}."}

                leg_coords = [[n[0], n[1]] for n in path]
                # Avoid duplicating the junction point between legs
                if all_coords and leg_coords:
                    leg_coords = leg_coords[1:]
                all_coords.extend(leg_coords)

                legs.append({
                    "from": wp_a.get("label", f"Stop {i+1}"),
                    "to": wp_b.get("label", f"Stop {i+2}"),
                    "distance_m": round(leg_len, 1),
                    "est_time_mins": round((leg_len / 11.1) / 60.0, 1)
                })
                total_dist += leg_len

            # Build output GeoJSON
            route_geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": all_coords},
                    "properties": {
                        "name": title,
                        "total_distance_m": round(total_dist, 1),
                        "total_est_time_mins": round((total_dist / 11.1) / 60.0, 1),
                        "stops": len(waypoints)
                    }
                }]
            }

            # Save waypoint markers too
            stop_features = []
            for idx, wp in enumerate(waypoints):
                stop_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(wp["lng"]), float(wp["lat"])]},
                    "properties": {
                        "stop_index": idx + 1,
                        "label": wp.get("label", f"Stop {idx+1}")
                    }
                })
            stops_geojson = {"type": "FeatureCollection", "features": stop_features}

            # Write files
            route_path = Path(workspace) / "multi_stop_route.geojson"
            stops_path = Path(workspace) / "multi_stop_waypoints.geojson"

            with open(route_path, "w") as f:
                json.dump(route_geojson, f)
            with open(stops_path, "w") as f:
                json.dump(stops_geojson, f)

            # Dispatch to map
            if ws:
                await ws.send_text(json.dumps({
                    "type": "action", "action": "add_geojson_file",
                    "payload": {"path": str(route_path), "name": title}
                }))
                await ws.send_text(json.dumps({
                    "type": "action", "action": "add_geojson_file",
                    "payload": {"path": str(stops_path), "name": f"{title} – Stops"}
                }))

            return {
                "status": "success",
                "total_stops": len(waypoints),
                "total_distance_m": round(total_dist, 1),
                "total_est_time_mins": round((total_dist / 11.1) / 60.0, 1),
                "legs": legs,
                "output_route": str(route_path)
            }

        except Exception as e:
            return {"error": f"Multi-stop routing failed: {str(e)}"}

