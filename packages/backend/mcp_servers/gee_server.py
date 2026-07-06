from __future__ import annotations
import os
from llm.base import ToolDeclaration

class GEEUnavailable(RuntimeError):
    pass

class GEEServer:
    description = "Google Earth Engine (GEE) dataset sampling and integration"
    tool_names = {"get_gee_layer"}

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
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "get_gee_layer":
            return await self._get_gee_layer(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _get_gee_layer(self, args: dict) -> dict:
        dataset = args.get("dataset", "").strip()
        lat = float(args.get("lat", 0))
        lng = float(args.get("lng", 0))
        radius = float(args.get("radius_meters", 1000))

        # Check for service account credentials
        creds = os.environ.get("GOOGLE_EARTH_ENGINE_CREDS")
        if not creds:
            return {
                "error": "Google Earth Engine service account credentials are not configured.",
                "code": "upstream_unavailable",
                "message": (
                    "Please set the GOOGLE_EARTH_ENGINE_CREDS environment variable "
                    "with your service account JSON file path or credentials string to enable Earth Engine integrations."
                ),
            }

        # If credentials are present, try importing ee and executing
        try:
            import ee
        except ImportError:
            return {
                "error": "Google Earth Engine python library ('earthengine-api') is not installed.",
                "code": "upstream_unavailable",
                "message": "Install earthengine-api via pip/poetry to run GEE tools.",
            }

        try:
            # Initialize Earth Engine
            if os.path.exists(creds):
                ee.Initialize(credentials=ee.ServiceAccountCredentials('', creds))
            else:
                import tempfile
                import json
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

            # Run a simple sample of the dataset at the point
            point = ee.Geometry.Point([lng, lat])
            
            try:
                image = ee.Image(dataset)
                val = image.sample(point, radius).first().serialize()
                return {
                    "status": "success",
                    "dataset": dataset,
                    "type": "Image",
                    "sample": val
                }
            except Exception:
                coll = ee.ImageCollection(dataset)
                first_img = coll.filterBounds(point).first()
                if first_img:
                    info = first_img.getInfo()
                    return {
                        "status": "success",
                        "dataset": dataset,
                        "type": "ImageCollection",
                        "first_image_info": info
                    }
                else:
                    return {"error": f"No images found bounds in dataset: {dataset}"}

        except Exception as e:
            return {
                "error": f"Google Earth Engine execution failed: {str(e)}",
                "code": "gee_error"
            }
