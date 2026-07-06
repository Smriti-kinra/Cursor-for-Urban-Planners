from __future__ import annotations
import httpx
from llm.base import ToolDeclaration
from routers.chat import _send_action

class WMSServer:
    description = "Web Map Service (WMS) layers integration"
    tool_names = {"add_wms_layer"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="add_wms_layer",
                description=(
                    "Add a custom WMS (Web Map Service) raster tile layer to the map. "
                    "Performs a GetCapabilities request to validate the WMS endpoint and layer name, "
                    "then displays the layer on the map."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The base URL of the WMS server (e.g. 'https://ahocevar.com/geoserver/wms')"},
                        "layer_name": {"type": "string", "description": "The technical name of the layer (e.g. 'topp:states')"},
                        "title": {"type": "string", "description": "Optional human-readable title for the layer list"},
                    },
                    "required": ["url", "layer_name"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "add_wms_layer":
            return await self._add_wms_layer(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _add_wms_layer(self, args: dict) -> dict:
        url = args.get("url", "").strip()
        layer_name = args.get("layer_name", "").strip()
        title = args.get("title", "").strip() or layer_name
        ws = args.get("_ws")

        if not url:
            return {"error": "url is required"}
        if not layer_name:
            return {"error": "layer_name is required"}

        # Validate URL/layer name using GetCapabilities query
        sep = "&" if "?" in url else "?"
        capabilities_url = f"{url}{sep}service=WMS&request=GetCapabilities"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get(capabilities_url)
                if res.status_code != 200:
                    return {"error": f"Failed to connect to WMS server. Status code: {res.status_code}"}
                
                content_str = res.text
                if f"<Name>{layer_name}</Name>" not in content_str and f"<Name>{layer_name} </Name>" not in content_str:
                    if layer_name.lower() not in content_str.lower():
                        return {"error": f"Layer '{layer_name}' not found in WMS Capabilities. Make sure the layer name is correct."}
        except Exception as e:
            return {"error": f"Failed to perform WMS GetCapabilities check: {str(e)}"}

        if ws:
            try:
                await _send_action(ws, "add_wms_layer", {
                    "url": url,
                    "layer_name": layer_name,
                    "title": title
                })
                return {"status": "success", "message": f"WMS layer '{title}' successfully added to the map."}
            except Exception as e:
                return {"error": f"Failed to transmit map action: {str(e)}"}
        else:
            return {"error": "WebSocket connection not available to send layer action."}
