from __future__ import annotations
import xml.etree.ElementTree as ET
import httpx
from llm.base import ToolDeclaration
from tools.action_utils import send_action

_WMS_TIMEOUT = 10.0


def _build_sep(url: str) -> str:
    return "&" if "?" in url else "?"


def _parse_layer_names(xml_text: str) -> list[str]:
    """Extract all <Name> text values from a WMS GetCapabilities response."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    names: list[str] = []
    seen: set[str] = set()
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "Name" and elem.text:
            n = elem.text.strip()
            if n and n not in seen:
                seen.add(n)
                names.append(n)
    return names


class WMSServer:
    description = "Web Map Service (WMS) layers integration"
    tool_names = {"add_wms_layer", "list_wms_layers"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="add_wms_layer",
                description=(
                    "Add a custom WMS (Web Map Service) raster tile layer to the map. "
                    "Performs a GetCapabilities request to validate the WMS endpoint and layer name, "
                    "then displays the layer on the map. If the user asks to add a WMS layer that "
                    "already exists on the map, make it visible instead of adding a duplicate."
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
            ToolDeclaration(
                name="list_wms_layers",
                description=(
                    "Fetch and return the list of all available layers from a WMS server by "
                    "running a GetCapabilities request. Use this to discover layer names before "
                    "calling add_wms_layer, or to re-validate a server after its layer list "
                    "may have changed."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The base URL of the WMS server"},
                    },
                    "required": ["url"],
                },
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "add_wms_layer":
            return await self._add_wms_layer(args)
        if tool_name == "list_wms_layers":
            return await self._list_wms_layers(args)
        return {"error": f"Unknown tool: {tool_name}"}

    async def _list_wms_layers(self, args: dict) -> dict:
        url = args.get("url", "").strip()
        if not url:
            return {"error": "url is required"}

        sep = _build_sep(url)
        caps_url = f"{url}{sep}service=WMS&request=GetCapabilities"
        try:
            async with httpx.AsyncClient(timeout=_WMS_TIMEOUT, follow_redirects=True) as client:
                res = await client.get(caps_url)
                if res.status_code != 200:
                    return {"error": f"WMS server returned HTTP {res.status_code}"}
                names = _parse_layer_names(res.text)
                return {"layers": names, "count": len(names)}
        except Exception as exc:
            return {"error": f"Failed to fetch WMS capabilities: {exc}"}

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
        sep = _build_sep(url)
        caps_url = f"{url}{sep}service=WMS&request=GetCapabilities"

        validation_warning = None
        try:
            async with httpx.AsyncClient(timeout=_WMS_TIMEOUT, follow_redirects=True) as client:
                res = await client.get(caps_url)
                if res.status_code == 200:
                    # Parse layer names properly to support nested group layers
                    available = _parse_layer_names(res.text)
                    # Case-sensitive exact match first, then case-insensitive fallback
                    exact = layer_name in available
                    fuzzy = any(n.lower() == layer_name.lower() for n in available)
                    if not exact and not fuzzy:
                        suggestions = ", ".join(available[:10]) if available else "(none found)"
                        return {
                            "error": (
                                f"Layer '{layer_name}' not found in WMS Capabilities. "
                                f"Available layers (first 10): {suggestions}"
                            )
                        }
                else:
                    validation_warning = f"GetCapabilities returned status code {res.status_code}."
        except Exception as e:
            validation_warning = f"GetCapabilities request failed or timed out: {str(e)}."

        if ws:
            try:
                await send_action(ws, "add_wms_layer", {
                    "url": url,
                    "layer_name": layer_name,
                    "title": title
                })
                msg = f"WMS layer '{title}' added to the map."
                if validation_warning:
                    msg += (
                        f"\n\n**Warning:** The validation check failed ({validation_warning}). "
                        "The layer was added to the sidebar, but since the server could not be reached, "
                        "the map tiles will likely display as blank/empty. Please verify that the "
                        "WMS URL and layer name are correct and that the server is online."
                    )
                return {"status": "success", "message": msg}


            except Exception as e:
                return {"error": f"Failed to transmit map action: {str(e)}"}
        else:
            return {"error": "WebSocket connection not available to send layer action."}
