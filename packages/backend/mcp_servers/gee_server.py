from __future__ import annotations
import os
import json
from pathlib import Path
from llm.base import ToolDeclaration

class GEEUnavailable(RuntimeError):
    pass

def _find_gee_creds() -> str | None:
    # 1. Check environment variable GOOGLE_EARTH_ENGINE_CREDS
    env_creds = os.environ.get("GOOGLE_EARTH_ENGINE_CREDS")
    if env_creds:
        return env_creds

    # 2. Check current working directory (workspace root) for service account JSON
    cwd = Path.cwd()
    # Search for files starting with ee- and ending with .json
    for p in cwd.glob("ee-*.json"):
        return str(p)
    # Search for any *.json that has type: service_account
    for p in cwd.glob("*.json"):
        try:
            with open(p, "r") as f:
                data = json.load(f)
                if data.get("type") == "service_account":
                    return str(p)
        except Exception:
            pass

    return None

def _get_dataset_defaults(dataset: str) -> tuple[dict, bool]:
    d_lower = dataset.lower()
    # Sentinel-2
    if "copernicus/s2" in d_lower:
        return {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}, True
    # Landsat 8/9
    if "landsat/lc08" in d_lower or "landsat/lc09" in d_lower:
        return {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 7000, "max": 30000}, True
    # SRTM Elevation
    if "srtm" in d_lower:
        return {"min": 0, "max": 2000, "palette": ["0000ff", "00ff00", "ffff00", "ff7f00", "ff0000"]}, False
    # ESA WorldCover
    if "worldcover" in d_lower:
        return {"bands": ["Map"]}, True
    # Generic fallback
    return {}, False


class GEEServer:
    description = "Google Earth Engine (GEE) — land cover, NDVI, LULC change, and raster visualization"
    tool_names = {"get_gee_layer", "add_gee_layer", "get_land_cover", "analyze_lulc_change", "get_ndvi_layer"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="get_gee_layer",
                description=(
                    "Retrieve raster sample metadata or statistics from a Google Earth Engine dataset. "
                    "Requires service account credentials configured in the active environment via "
                    "GOOGLE_EARTH_ENGINE_CREDS (a JSON string or path to a credentials JSON file)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset": {"type": "string", "description": "The Earth Engine dataset ID (e.g. 'USGS/SRTMGL1_003' or 'COPERNICUS/S2_SR')"},
                        "lat": {"type": "number", "description": "Latitude coordinate of the point to sample"},
                        "lng": {"type": "number", "description": "Longitude coordinate of the point to sample"},
                        "radius_meters": {"type": "number", "description": "Radius in meters to buffer and sample features (default 1000)"},
                    },
                    "required": ["dataset", "lat", "lng"],
                },
            ),
            ToolDeclaration(
                name="add_gee_layer",
                description=(
                    "Add a Google Earth Engine raster layer and display it on the map as a tiled imagery layer. "
                    "Automatically handles Sentinel-2, Landsat, and SRTM elevation visualization params, "
                    "and performs cloud-free median compositing for collections over a specified year/date."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "dataset": {
                            "type": "string",
                            "description": "Earth Engine dataset ID (e.g., 'COPERNICUS/S2_SR_HARMONIZED', 'USGS/SRTMGL1_003')."
                        },
                        "vis_params": {
                            "type": "object",
                            "description": "Optional: GEE visualization params (e.g., {\"min\":0,\"max\":3000,\"bands\":[\"B4\",\"B3\",\"B2\"]})."
                        },
                        "date": {
                            "type": "string",
                            "description": "Optional: Year (e.g., '2023') or specific date (e.g., '2023-06-01') to filter ImageCollections."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional: Title for the map layer list (e.g. 'Sentinel-2 RGB 2023')."
                        }
                    },
                    "required": ["dataset"]
                }
            ),
            ToolDeclaration(
                name="get_land_cover",
                description=(
                    "Fetch and display a Google Dynamic World or ESA WorldCover land-use / land-cover (LULC) layer "
                    "for a specific year. Renders a coloured classification map on the map canvas. "
                    "Supported sources: 'dynamic_world' (Google, 2016–present, 10m, 9 classes: water/trees/grass/"
                    "flooded-veg/crops/shrub/built/bare/snow) and 'esa_worldcover' (ESA, 2020/2021, 10m, 11 classes). "
                    "Use this for land-use mapping, urban footprint detection, and green space analysis."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["dynamic_world", "esa_worldcover"],
                            "description": "Land cover dataset. 'dynamic_world' = Google 10m annual; 'esa_worldcover' = ESA 10m 2020/2021."
                        },
                        "year": {
                            "type": "integer",
                            "description": "Year to visualize (e.g. 2022). For ESA WorldCover use 2020 or 2021."
                        },
                        "title": {
                            "type": "string",
                            "description": "Label for this layer in the map layer list."
                        }
                    },
                    "required": ["source"]
                }
            ),
            ToolDeclaration(
                name="analyze_lulc_change",
                description=(
                    "Compare Google Dynamic World land cover composites across two years to detect land-use change. "
                    "Returns two layers: (1) a binary changed/unchanged mask, (2) a class-transition layer. "
                    "Highlights urban growth, deforestation, wetland loss, or agricultural expansion. "
                    "Requires GEE credentials."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "year_start": {
                            "type": "integer",
                            "description": "Start year for comparison (e.g. 2018)."
                        },
                        "year_end": {
                            "type": "integer",
                            "description": "End year for comparison (e.g. 2023)."
                        },
                        "title": {
                            "type": "string",
                            "description": "Label for the change detection layer."
                        }
                    },
                    "required": ["year_start", "year_end"]
                }
            ),
            ToolDeclaration(
                name="get_ndvi_layer",
                description=(
                    "Compute and display an NDVI (Normalized Difference Vegetation Index) layer from Sentinel-2 "
                    "for a given year. NDVI > 0.4 = dense vegetation; < 0.1 = built-up or bare land. "
                    "Use for urban heat island analysis, park mapping, and vegetation health monitoring."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "year": {
                            "type": "integer",
                            "description": "Year to compute NDVI for (e.g. 2023)."
                        },
                        "title": {
                            "type": "string",
                            "description": "Layer name (e.g. 'NDVI 2023 — Chandigarh')."
                        }
                    },
                    "required": ["year"]
                }
            )
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "get_gee_layer":
            return await self._get_gee_layer(args)
        if tool_name == "add_gee_layer":
            return await self._add_gee_layer(args)
        if tool_name == "get_land_cover":
            return await self._get_land_cover(args)
        if tool_name == "analyze_lulc_change":
            return await self._analyze_lulc_change(args)
        if tool_name == "get_ndvi_layer":
            return await self._get_ndvi_layer(args)
        return {"error": f"Unknown tool: {tool_name}"}

    # ── Shared GEE init helper ────────────────────────────────────────────────

    def _init_gee(self) -> tuple[bool, str | None]:
        """Initialize GEE with service account credentials. Returns (ok, error_message)."""
        creds = _find_gee_creds()
        if not creds:
            return False, (
                "Google Earth Engine credentials not configured. "
                "Drop your ee-*.json service account file into the workspace root."
            )
        try:
            import ee
            if os.path.exists(creds):
                with open(creds) as f:
                    creds_data = json.load(f)
                service_account = creds_data.get("client_email", "")
                credentials = ee.ServiceAccountCredentials(service_account, creds)
            else:
                import tempfile
                creds_data = json.loads(creds)
                service_account = creds_data.get("client_email", "")
                with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
                    f.write(creds)
                    tmp = f.name
                credentials = ee.ServiceAccountCredentials(service_account, tmp)
                os.unlink(tmp)
            ee.Initialize(credentials=credentials)
            return True, None
        except ImportError:
            return False, "earthengine-api not installed. Run: pip install earthengine-api"
        except Exception as e:
            return False, f"GEE initialization failed: {e}"

    async def _get_gee_layer(self, args: dict) -> dict:
        dataset = args.get("dataset", "").strip()
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        radius = float(args.get("radius_meters", 1000))

        creds = _find_gee_creds()
        if not creds:
            return {
                "error": "Google Earth Engine service account credentials are not configured.",
                "code": "upstream_unavailable",
                "message": (
                    "Please set the GOOGLE_EARTH_ENGINE_CREDS environment variable "
                    "or drop your credentials JSON file into the workspace root."
                ),
            }

        try:
            import ee
        except ImportError:
            return {
                "error": "Google Earth Engine python library ('earthengine-api') is not installed.",
                "code": "upstream_unavailable",
                "message": "Install earthengine-api via pip/poetry to run GEE tools.",
            }

        try:
            if os.path.exists(creds):
                ee.Initialize(credentials=ee.ServiceAccountCredentials('', creds))
            else:
                import tempfile
                try:
                    json.loads(creds)
                    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
                        f.write(creds)
                        temp_path = f.name
                    ee.Initialize(credentials=ee.ServiceAccountCredentials('', temp_path))
                    os.unlink(temp_path)
                except Exception as je:
                    return {
                        "error": f"Failed to parse GOOGLE_EARTH_ENGINE_CREDS JSON or path: {str(je)}",
                        "code": "invalid_credentials"
                    }

            point = ee.Geometry.Point([lng, lat])

            try:
                image = ee.Image(dataset)
                val = image.sample(point, radius).first().serialize()
                return {"status": "success", "dataset": dataset, "type": "Image", "sample": val}
            except Exception:
                coll = ee.ImageCollection(dataset)
                first_img = coll.filterBounds(point).first()
                if first_img:
                    info = first_img.getInfo()
                    return {"status": "success", "dataset": dataset, "type": "ImageCollection", "first_image_info": info}
                else:
                    return {"error": f"No images found in dataset: {dataset}"}

        except Exception as e:
            return {"error": f"Google Earth Engine execution failed: {str(e)}", "code": "gee_error"}

    async def _add_gee_layer(self, args: dict) -> dict:
        dataset = args.get("dataset", "").strip()
        vis_params = args.get("vis_params") or {}
        date_str = args.get("date", "").strip()
        title = args.get("title", "").strip() or f"{dataset} Layer"
        ws = args.get("_ws")

        if not dataset:
            return {"error": "dataset is required"}

        creds = _find_gee_creds()
        if not creds:
            return {"error": "GEE credentials not configured.", "code": "upstream_unavailable"}

        try:
            import ee
        except ImportError:
            return {"error": "earthengine-api not installed.", "code": "upstream_unavailable"}

        try:
            if os.path.exists(creds):
                ee.Initialize(credentials=ee.ServiceAccountCredentials('', creds))
            else:
                import tempfile
                json.loads(creds)
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
                    f.write(creds)
                    temp_path = f.name
                ee.Initialize(credentials=ee.ServiceAccountCredentials('', temp_path))
                os.unlink(temp_path)

            default_vis, is_collection = _get_dataset_defaults(dataset)
            final_vis = {**default_vis, **vis_params}

            if is_collection:
                coll = ee.ImageCollection(dataset)
                if date_str:
                    start = f"{date_str}-01-01" if len(date_str) == 4 else date_str
                    end = f"{date_str.split('-')[0]}-12-31"
                    coll = coll.filterDate(start, end)
                if "copernicus/s2" in dataset.lower():
                    coll = coll.filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10))
                elif "landsat" in dataset.lower():
                    coll = coll.filter(ee.Filter.lt('CLOUD_COVER', 10))
                img = coll.median()
            else:
                img = ee.Image(dataset)

            map_id_dict = ee.data.getMapId({'image': img, 'visParams': final_vis})
            tile_url = map_id_dict['tile_fetcher'].url_format

            if ws:
                await ws.send_text(json.dumps({
                    "type": "action", "action": "add_gee_layer",
                    "payload": {"url": tile_url, "dataset": dataset, "vis_params": final_vis, "title": title}
                }))
                return {"status": "success", "message": f"GEE layer '{title}' added to map."}
            return {"status": "success", "tile_url": tile_url}

        except Exception as e:
            return {"error": f"GEE execution failed: {str(e)}", "code": "gee_error"}

    # ── Land Classification Tools ─────────────────────────────────────────────

    async def _get_land_cover(self, args: dict) -> dict:
        source = args.get("source", "dynamic_world").strip()
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip()
        ws = args.get("_ws")

        ok, err = self._init_gee()
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            if source == "dynamic_world":
                dw = (
                    ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
                    .filterDate(f"{year}-01-01", f"{year}-12-31")
                    .select("label")
                    .mode()
                )
                dw_palette = [
                    "419BDF", "397D49", "88B053", "7A87C6",
                    "E49635", "DFC35A", "C4281B", "A59B8F", "B39FE1"
                ]
                dw_classes = [
                    "Water", "Trees", "Grass", "Flooded Vegetation",
                    "Crops", "Shrub & Scrub", "Built Area", "Bare Ground", "Snow & Ice"
                ]
                vis = {"min": 0, "max": 8, "palette": dw_palette}
                layer_title = title or f"Dynamic World Land Cover {year}"

                map_id = ee.data.getMapId({"image": dw, "visParams": vis})
                tile_url = map_id["tile_fetcher"].url_format

                if ws:
                    await ws.send_text(json.dumps({
                        "type": "action", "action": "add_gee_layer",
                        "payload": {"url": tile_url, "dataset": "GOOGLE/DYNAMICWORLD/V1",
                                    "vis_params": vis, "title": layer_title}
                    }))
                return {
                    "status": "success",
                    "source": "Google Dynamic World V1",
                    "year": year,
                    "classes": {str(i): {"name": n, "color": f"#{c}"}
                                for i, (n, c) in enumerate(zip(dw_classes, dw_palette))},
                    "message": f"Land cover layer '{layer_title}' added to map."
                }

            elif source == "esa_worldcover":
                yr_map = {2020: "ESA/WorldCover/v100/2020", 2021: "ESA/WorldCover/v200/2021"}
                dataset_id = yr_map.get(year, "ESA/WorldCover/v200/2021")
                img = ee.ImageCollection(dataset_id).first()
                esa_palette = [
                    "006400", "ffbb22", "ffff4c", "f096ff",
                    "fa0000", "b4b4b4", "f0f0f0", "0064c8",
                    "0096a0", "00cf75", "fae6a0"
                ]
                vis = {"bands": ["Map"], "min": 10, "max": 100, "palette": esa_palette}
                layer_title = title or f"ESA WorldCover {year}"

                map_id = ee.data.getMapId({"image": img, "visParams": vis})
                tile_url = map_id["tile_fetcher"].url_format

                if ws:
                    await ws.send_text(json.dumps({
                        "type": "action", "action": "add_gee_layer",
                        "payload": {"url": tile_url, "dataset": dataset_id,
                                    "vis_params": vis, "title": layer_title}
                    }))
                return {
                    "status": "success",
                    "source": "ESA WorldCover",
                    "dataset": dataset_id,
                    "message": f"Land cover layer '{layer_title}' added to map."
                }

            return {"error": f"Unknown source '{source}'. Use 'dynamic_world' or 'esa_worldcover'."}

        except Exception as e:
            return {"error": f"Land cover layer failed: {e}", "code": "gee_error"}

    async def _analyze_lulc_change(self, args: dict) -> dict:
        year_start = int(args.get("year_start", 2018))
        year_end = int(args.get("year_end", 2023))
        title = args.get("title", "").strip() or f"LULC Change {year_start}→{year_end}"
        ws = args.get("_ws")

        if year_start >= year_end:
            return {"error": "year_start must be less than year_end"}

        ok, err = self._init_gee()
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            def mode_for_year(y: int):
                return (
                    ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
                    .filterDate(f"{y}-01-01", f"{y}-12-31")
                    .select("label").mode()
                )

            lc_start = mode_for_year(year_start)
            lc_end = mode_for_year(year_end)
            changed = lc_start.neq(lc_end)

            # Class transition image: start_class*10 + end_class, masked to changed pixels only
            transition = lc_start.multiply(10).add(lc_end).updateMask(changed)

            changed_vis = {"min": 0, "max": 1, "palette": ["cccccc", "ff4444"]}
            transition_vis = {"min": 0, "max": 88, "palette": [
                "ffffff", "ff0000", "00aaff", "ffcc00",
                "88cc00", "cc4400", "4400cc", "00cc88", "880000"
            ]}

            changed_tile = ee.data.getMapId({"image": changed.rename("changed"), "visParams": changed_vis})["tile_fetcher"].url_format
            transition_tile = ee.data.getMapId({"image": transition, "visParams": transition_vis})["tile_fetcher"].url_format

            if ws:
                await ws.send_text(json.dumps({
                    "type": "action", "action": "add_gee_layer",
                    "payload": {"url": changed_tile, "dataset": "GOOGLE/DYNAMICWORLD/V1",
                                "vis_params": changed_vis, "title": f"Changed Areas {year_start}→{year_end}"}
                }))
                await ws.send_text(json.dumps({
                    "type": "action", "action": "add_gee_layer",
                    "payload": {"url": transition_tile, "dataset": "GOOGLE/DYNAMICWORLD/V1",
                                "vis_params": transition_vis, "title": title}
                }))

            return {
                "status": "success",
                "year_start": year_start,
                "year_end": year_end,
                "layers_added": 2,
                "message": (
                    f"LULC change layers added: (1) changed/unchanged mask, "
                    f"(2) class transition map. Red = land converted; class transitions "
                    f"encoded as (start_class×10 + end_class)."
                )
            }

        except Exception as e:
            return {"error": f"LULC change analysis failed: {e}", "code": "gee_error"}

    async def _get_ndvi_layer(self, args: dict) -> dict:
        year = int(args.get("year") or 2023)
        title = args.get("title", "").strip() or f"NDVI {year}"
        ws = args.get("_ws")

        ok, err = self._init_gee()
        if not ok:
            return {"error": err, "code": "upstream_unavailable"}

        try:
            import ee

            s2 = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterDate(f"{year}-01-01", f"{year}-12-31")
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 10))
                .select(["B8", "B4"])
                .median()
            )
            ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI")

            ndvi_palette = ["8B4513", "D2691E", "F4A460", "FFFF00", "9ACD32", "228B22", "006400"]
            vis = {"min": -0.1, "max": 0.8, "palette": ndvi_palette}

            map_id = ee.data.getMapId({"image": ndvi, "visParams": vis})
            tile_url = map_id["tile_fetcher"].url_format

            if ws:
                await ws.send_text(json.dumps({
                    "type": "action", "action": "add_gee_layer",
                    "payload": {"url": tile_url, "dataset": "COPERNICUS/S2_SR_HARMONIZED",
                                "vis_params": vis, "title": title}
                }))

            return {
                "status": "success",
                "year": year,
                "index": "NDVI",
                "interpretation": {
                    "< 0.1": "Built-up / bare land / water",
                    "0.1 – 0.3": "Sparse vegetation / degraded land",
                    "0.3 – 0.5": "Moderate vegetation (agriculture, parks)",
                    "> 0.5": "Dense vegetation / forest"
                },
                "message": f"NDVI layer '{title}' added to map."
            }

        except Exception as e:
            return {"error": f"NDVI computation failed: {e}", "code": "gee_error"}
