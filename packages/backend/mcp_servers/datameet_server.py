from __future__ import annotations
from pathlib import Path
import httpx
from llm.base import ToolDeclaration
from tools.action_utils import send_action

class DatameetServer:
    description = "DataMeet boundaries downloader (States, Districts, Villages)"
    tool_names = {"import_datameet_boundary"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="import_datameet_boundary",
                description=(
                    "Fetch and display state, district, or village boundaries from Datameet map data source. "
                    "Downloads the GeoJSON dynamically, saves it into the active workspace, and displays it on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": ["state", "district", "village"],
                            "description": "Administrative level to retrieve"
                        },
                        "state_code": {
                            "type": "string",
                            "description": "ISO state code (e.g. 'ka' for Karnataka, 'mh' for Maharashtra, 'gj' for Gujarat, 'rj' for Rajasthan). Required if level is 'village'."
                        },
                        "workspace": {
                            "type": "string",
                            "description": "Absolute path to the active workspace folder"
                        },
                    },
                    "required": ["level", "workspace"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "import_datameet_boundary":
            return await self._import_boundary(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _import_boundary(self, args: dict) -> dict:
        level = args.get("level", "").strip().lower()
        state_code = args.get("state_code", "").strip().lower()
        workspace = args.get("workspace", "").strip()
        ws = args.get("_ws")

        if not workspace:
            return {"error": "workspace path is required to save boundaries"}
        
        workspace_path = Path(workspace)
        if not workspace_path.exists():
            return {"error": f"Workspace path does not exist: {workspace}"}

        # Determine download URL and target name
        if level == "state":
            url = "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/INDIA/INDIA_STATES.geojson"
            filename = "india_states.geojson"
        elif level == "district":
            url = "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/INDIA/INDIA_DISTRICTS.geojson"
            filename = "india_districts.geojson"
        elif level == "village":
            if not state_code:
                return {"error": "state_code is required for village boundaries"}
            url = f"https://raw.githubusercontent.com/datameet/indian_village_boundaries/master/{state_code}/{state_code}.json"
            filename = f"village_boundaries_{state_code}.geojson"
        else:
            return {"error": f"Invalid level: {level}"}

        target_file = workspace_path / filename

        # Check if file already exists in workspace
        if target_file.exists():
            if ws:
                try:
                    await send_action(ws, "add_geojson_file", {
                        "path": str(target_file.resolve()),
                        "name": filename.replace(".geojson", "").replace("_", " ").title()
                    })
                    return {
                        "status": "already_imported",
                        "path": str(target_file.resolve()),
                        "message": f"Boundaries file '{filename}' was already present in the workspace and loaded."
                    }
                except Exception as e:
                    return {"error": f"Failed to send map action: {str(e)}"}
            else:
                return {"error": "WebSocket connection not available to send load action."}

        # Download the file dynamically
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        return {"error": f"Failed to download boundary file from source. Status code: {response.status_code}"}
                    
                    temp_file = workspace_path / f"{filename}.tmp"
                    with open(temp_file, "wb") as f:
                        async for chunk in response.iter_bytes(chunk_size=32768):
                            f.write(chunk)
                    
                    if temp_file.exists():
                        temp_file.rename(target_file)
        except Exception as e:
            temp_file = workspace_path / f"{filename}.tmp"
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except:
                    pass
            return {"error": f"Failed to download boundary file: {str(e)}"}

        # Instruct client to load it
        if ws:
            try:
                await send_action(ws, "add_geojson_file", {
                    "path": str(target_file.resolve()),
                    "name": filename.replace(".geojson", "").replace("_", " ").title()
                })
                return {
                    "status": "success",
                    "path": str(target_file.resolve()),
                    "message": f"Boundaries file '{filename}' successfully downloaded and loaded."
                }
            except Exception as e:
                return {"error": f"Failed to send map action: {str(e)}"}
        else:
            return {"error": "WebSocket connection not available to send load action."}
