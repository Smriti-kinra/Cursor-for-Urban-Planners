# AGENTS.md

Orientation for Codex working in this repo. Read this first; then jump to the file you need.

## What this is

A geospatial-first AI-driven IDE for urban planners. Electron desktop app + Python backend. Users chat with an LLM that drives a MapLibre map via tool calls — fly to places, fetch OSM features, draw zoning, run GIS analysis, save artifacts.

**Quality bar:** solid prototype. Golden paths must work and not crash. Tests are not required yet, but don't introduce regressions in the chat → tool-call → map-action flow.

## Architecture in 10 lines

```
Electron main (apps/desktop/src/main/index.ts)
  ├─ spawns FastAPI backend on :8765 (PyInstaller-frozen in prod, uvicorn in dev)
  └─ creates BrowserWindow → loads renderer (React)

Renderer (apps/desktop/src/renderer/) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws   ← streaming chat + tool calls
  ├─ Backend over HTTP       /api/files /api/artifacts /api/reports
  └─ Electron main over IPC  (file dialogs, read directory, switch model)

Backend (packages/backend/) talks to:
  └─ OpenAI HTTPS  (key from OPENAI_API_KEY env)
     + Overpass, Nominatim, OSRM, Open-Meteo (free, keyless)
```

## The three communication channels

| Channel | Used for |
|---|---|
| **WebSocket** (renderer ↔ backend) | Streaming chat, tool calls, map actions. Lives in `ChatPanel.tsx` ↔ `routers/chat.py:chat_websocket`. |
| **HTTP** (renderer ↔ backend) | List workspace files, CRUD on artifacts, generate Markdown reports. Routers in `packages/backend/routers/`. |
| **Electron IPC** (renderer ↔ main) | Local OS only — open file picker, read a directory, persist last-workspace, switch model. Surface defined in `apps/desktop/src/preload/index.ts`. |

## The MCP server pattern

Each domain server in `packages/backend/mcp_servers/` is a class with three things:

```python
class FooServer:
    description: str
    tool_names: set[str]                                # {"foo_do_x", "foo_do_y"}
    def get_declarations(self) -> list[ToolDeclaration]: ...
    async def execute(self, tool_name: str, args: dict) -> dict: ...
```

Servers in use: `osm_server.py`, `gis_server.py`, `weather_server.py`, `zoning_server.py`, `demographics_server.py`, `overture_server.py`, `google_places_server.py`, `google_environment_server.py`, `network_server.py`, `od_server.py`, `gee_server.py`, `datameet_server.py`, `gtfs_server.py`, `wms_server.py`, `scenario_server.py`, plus `tools/utility.py` (the shared `UtilityServer` for `web_search`, `geocode`, `measure_*`, `create_artifact`, `georeference_active_document`, `digitize_image_features`). They are instantiated once in `routers/chat.py:_servers` and their tools are flattened into the OpenAI function-tool list by `_build_tools()`.

## The action contract

When the model calls a function whose name is in `_ACTION_TOOLS` (`routers/chat.py:61`), the backend forwards it to the renderer over the WebSocket as:

```json
{ "type": "action", "action": "<name>", "payload": { ...args } }
```

`MapView.tsx` consumes these via the `mapActions` queue from `App.tsx` and turns them into MapLibre operations (fly, fit_bounds, add_marker, add_geojson, draw_line, etc.). To add a new action you must touch **both ends** — backend tool def + frontend handler. See the `add-map-action` skill (in `.Codex/skills/`) for the procedure.

## Tool dispatch

All tool logic flows through `packages/backend/routers/chat.py`:

- Servers are instantiated in `_servers`, their `get_declarations()` is flattened into the OpenAI tool list by `_build_tools()`, and dispatch happens in `_execute_tool()`.
- Adding a domain tool means editing a single MCP server class and nothing else — the flatten step picks it up automatically. `UtilityServer` (in `tools/utility.py`) is the home for cross-cutting tools (`web_search`, `geocode`, `measure_distance`, `measure_area`, `create_artifact`).
- Action tools (the names in `_ACTION_TOOLS`) need the OpenAI schema in `_build_tools()` plus a frontend handler in `MapView.tsx`. Use the `add-map-action` skill.

There is no external MCP stdio bridge — the in-app chat is the only surface.

## Geospatial conventions

- **Coordinates everywhere are EPSG:4326 lat/lng.** No reprojection is performed anywhere in the codebase.
- **Shapely operates on raw lat/lng**, so `.area` is in degree² (meaningless). The `gis_area` tool in `gis_server.py` and the `measure_area` tool in `tools/utility.py` use a homegrown spherical shoelace approximation. Acceptable for small polygons; diverges from geodesic on large ones. Don't introduce code that assumes a projected CRS.
- **Tile sources are free raster XYZ** (OSM, CartoDB, Esri, OpenTopoMap). No Mapbox token, no PMTiles, no MBTiles. Defined in `apps/desktop/src/renderer/types.ts:BASEMAPS`.
- **OSM data path** is Overpass API → `_merge_ways()` ring-merge → GeoJSON Feature. Boundary fetches additionally fall through to Nominatim with `polygon_geojson=1`.
- **Frontend geometry ops use Turf.js** (`@turf/turf`).

## Frontend state

Pure React `useState`/`useRef`. **No** Zustand/Redux/Context. All state lives in `App.tsx` and flows down as props. `MapView` exposes a ref (`MapViewHandle`) for canvas access. `mapActions` is a queue array; `MapView` processes and clears via `onActionsProcessed`. Don't add a state library — match the existing pattern.

## Run instructions

```bash
pnpm install                # once
cd packages/backend && python -m venv .buildenv && \
  source .buildenv/bin/activate && pip install -r requirements.txt   # once
export OPENAI_API_KEY=...

pnpm dev                    # starts backend (uvicorn :8765) + renderer (electron-vite)
```

In dev, `apps/desktop/src/main/index.ts:startBackend` is a no-op — uvicorn runs separately via `pnpm dev:backend`. In prod (`pnpm package`), the PyInstaller binary is spawned by Electron from `Resources/backend/backend`.

## Key files to read first (in order)

1. `packages/backend/routers/chat.py` — agentic loop, action contract, tool registry. **The heart of the AI behavior.**
2. `apps/desktop/src/renderer/App.tsx` — single state container, component wiring, conversation persistence.
3. `apps/desktop/src/renderer/components/MapView.tsx` — MapLibre setup + action handlers.
4. `apps/desktop/src/renderer/components/ChatPanel.tsx` — WebSocket client, streaming render.
5. `packages/backend/mcp_servers/osm_server.py` — canonical MCP server example with the most logic.
6. `apps/desktop/src/renderer/types.ts` — shared interfaces, basemap defs, zone presets, layer colors.
7. `apps/desktop/src/preload/index.ts` — full IPC surface between renderer and Electron main.

## Known debt and gaps

- **No tests.** Anywhere. The agent loop, OSM ring-merge, and area math are entirely untested.
- **DocumentView PDF mode is display-only** — PDFs render in an iframe but cannot be sent to OpenAI vision (no PDF→image conversion).

## How to work in this repo with Codex

- **Adding an MCP tool?** Use the `add-mcp-tool` skill — domain tools land in one server file and auto-register everywhere; cross-cutting tools extend `UtilityServer`.
- **Adding a map action?** Use the `add-map-action` skill — touches the backend action contract in `chat.py` and the frontend handler in `MapView.tsx` together.
- **Designing a new feature?** Start with `superpowers:brainstorming`, then `superpowers:writing-plans`. Don't dive into code until the plan exists.
- **Debugging the agent loop?** Use `superpowers:systematic-debugging`. The loop is in `_run_agent()` — streaming tool-call deltas accumulate in `tool_calls_acc`, then execute, then loop until `finish_reason == "stop"`.
- **Looking up MapLibre / FastAPI / OpenAI SDK docs?** Use `context7` — your training cutoff is older than these libraries' current versions.
- **Before claiming a UI change works**, run the app (`run` skill) and exercise the change in the Electron window. Type-check passing is not the same as feature working.
