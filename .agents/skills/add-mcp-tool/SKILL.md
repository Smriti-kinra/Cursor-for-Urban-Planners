---
name: add-mcp-tool
description: Use when adding a new backend tool the AI agent can call (OSM query, GIS operation, weather lookup, demographic stat, etc.). Encodes the procedure across the MCP server class and the in-app chat router.
---

# Add MCP Tool

A "tool" is a function the LLM can call during a chat. There are three categories in this repo and the procedure differs for each.

## Three categories of tools

| Category | Where it lives | Files to touch |
|---|---|---|
| **MCP server tool** (a domain operation: `osm_search`, `gis_buffer`, `get_weather`) | A class in `packages/backend/mcp_servers/*.py` | One server file. Auto-registered. |
| **Action tool** (a map operation the frontend executes: `fly_to`, `add_geojson`, `draw_line`) | The action contract crossing backend → WebSocket → `MapView.tsx` | **Use the [[add-map-action]] skill instead.** |
| **Utility tool** (cross-cutting: `web_search`, `geocode`, `measure_distance`, `create_artifact`) | `UtilityServer` in `packages/backend/tools/utility.py` | One file. Auto-registered via `_servers["utility"]`. |

**The default answer is "MCP server tool."** If the tool is a domain operation (querying OSM, computing GIS, fetching weather, looking up demographics, analyzing zones), put it in the matching server class. If it's cross-cutting (search, geocoding, measurement, artifact storage), extend `UtilityServer` — same pattern, same auto-registration.

## Procedure: adding an MCP server tool

### 1. Pick or create the server

| If the tool is about… | Use server | File |
|---|---|---|
| OSM features, boundaries, geocoding, routing | `OSMServer` | `mcp_servers/osm_server.py` |
| GIS operations on geometry (buffer, area, hull, union, point-in-polygon) | `GISServer` | `mcp_servers/gis_server.py` |
| Weather / air quality | `WeatherServer` | `mcp_servers/weather_server.py` |
| Zoning analysis, overlap detection | `ZoningServer` | `mcp_servers/zoning_server.py` |
| Population, density, demographics | `DemographicsServer` | `mcp_servers/demographics_server.py` |

If none fit, **create a new server**. Mirror `weather_server.py` exactly — it's the cleanest example: ~150 lines, two tools, no I/O quirks.

A new server is a class with three things:
```python
from llm.base import ToolDeclaration

class FooServer:
    description = "..."
    tool_names = {"foo_op_a", "foo_op_b"}

    def get_declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(
                name="foo_op_a",
                description="...",
                parameters={"type": "object", "properties": {...}, "required": [...]},
            ),
        ]

    async def execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "foo_op_a":
            return await self._foo_op_a(args)
        return {"error": f"Unknown tool: {tool_name}"}
```

Then register the new server in `packages/backend/routers/chat.py` `_servers` dict (around line 48). That's the only edit outside the new server file.

### 2. Add the tool to the server

In the chosen server file, edit three places:

**a.** Add the tool name to `tool_names` (the `set[str]` near the top of the class).
**b.** Add a `ToolDeclaration` to `get_declarations()`. Use a JSON Schema object for `parameters`.
**c.** Add a branch in `execute()` and an implementation method.

That's it. Tools added this way are **auto-flattened** into the OpenAI tool list at `routers/chat.py:_build_tools()` — the loop is `for srv in _servers.values(): for decl in srv.get_declarations(): tools.append(...)`.

**No edits to `chat.py` are required for the tool to be callable.**

### 3. Auto-display (only if the tool returns map-displayable geometry)

If your tool returns `{"geojson": ...}` or `{"geometry": ...}` that should appear on the map automatically (without the model having to call `add_geojson` afterwards), add a branch in `routers/chat.py:_execute_tool()`. Search for `# Auto-display osm_search result on map` to find the existing block.

Pattern (use `osm_boundary` as the simplest reference):
```python
elif name == "your_new_tool" and "geojson" in result:
    label = args.get("name", "Result")
    await _send_action(ws, "add_geojson", {"geojson": result["geojson"], "name": label})
    result = {"name": result.get("name", ""), "displayed_on_map": True}
```

The shape collapses the response so the model doesn't waste tokens echoing the geometry it just rendered.

### 4. Tell the model the tool exists

Edit `SYSTEM_PROMPT` in `routers/chat.py`. Find the matching category in the `AVAILABLE TOOLS:` list and add your tool name. Without this the model rarely calls new tools — they show up in the tool schema but the prompt is what biases selection.

If your tool needs a specific calling convention (e.g., "always pass `country_code`"), add it under `IMPORTANT RULES:` lower in the prompt.

### 5. Verify

```bash
pnpm dev
```

Then in the chat panel, ask something that should trigger your tool. Confirm:
- The tool fires (check the streamed `[tool_call]` chunks in the chat).
- The result is what you expect (auto-display branch fires if applicable).
- No `Unknown tool: ...` error.

## Adding a utility tool

Cross-cutting tools (`web_search`, `geocode`, `measure_distance`, `measure_area`, `create_artifact`) live in `packages/backend/tools/utility.py` as the `UtilityServer` class. The pattern is identical to a domain server:

1. Add the tool name to `UtilityServer.tool_names`.
2. Add a `ToolDeclaration` to `get_declarations()`.
3. Add a branch in `execute()` and an implementation method on the class.

Auto-registration handles the rest — `chat.py` has `"utility": UtilityServer(db_path=DB_PATH)` in its `_servers` dict.

**One side-effect to know about:** `create_artifact` returns `{"status": "created", "id": <int>}` — it does NOT fire the `refresh_artifacts` UI action. `chat.py:_execute_tool()` detects the tool name after dispatch and emits that side-effect itself. If your new utility tool needs a similar UI side-effect, follow the same pattern (caller emits the action, not the server).

**Before adding to `UtilityServer`:** ask whether the tool actually fits a domain server. `web_search` could plausibly live in a new `SearchServer`. `geocode` overlaps with `OSMServer`. The utility bucket is for things that are genuinely orthogonal to any domain.

## Files referenced

- `packages/backend/routers/chat.py` — `_servers` dict, `_ACTION_TOOLS`, `SYSTEM_PROMPT`, `_build_tools()`, `_execute_tool()`.
- `packages/backend/mcp_servers/weather_server.py` — cleanest server template (~150 lines).
- `packages/backend/tools/utility.py` — `UtilityServer` (cross-cutting tools).
- `packages/backend/llm/base.py` — `ToolDeclaration` dataclass.

Line numbers drift; grep by the comment headers (`# ── Action tool names`, `# ── Build OpenAI tool definitions`, `# ── Tool execution`) to locate sections reliably.
