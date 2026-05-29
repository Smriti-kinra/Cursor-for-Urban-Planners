# Cursor for Urban Planners — Architecture & Features

A geospatial-first AI-driven IDE for urban planners. The user chats with an LLM that drives a live MapLibre map, runs OSM/GIS queries, drafts zoning, and saves planning artifacts — all inside an offline-capable Electron desktop app.

This document is split into two halves:

- **Part 1 — For Users.** What the app does and how to use it.
- **Part 2 — For Developers.** How the system is wired together.

If you only want the orientation needed to make code changes, jump to Part 2.

---

# Part 1 — For Users

## What it is

A desktop app (macOS / Windows / Linux) that combines four panes:

| Pane | Purpose |
|---|---|
| **Map** (center, Map mode) | Interactive MapLibre canvas with switchable basemaps, layer rendering, marker pins, drawn shapes |
| **Document view** (center, Document mode) | Drop in a planning PDF or map image and have the AI analyze it |
| **Left panel** | Files · Layers · Bookmarks · Export · Zoning legend |
| **Right panel** | Chat · Artifacts |

You toggle between **Map** and **Document** modes from the title bar. Map mode is the primary surface; Document mode is for one-off analysis of external planning documents.

## Workspace

Open a folder via the title-bar button. The app:

- Lists `.geojson` and other files in **Files** (click a `.geojson` to load it as a map layer).
- Auto-saves a `project.json` in the workspace folder containing your map state, layers, conversations, bookmarks, and basemap.
- Materializes any chat-generated layers into `<workspace>/.cursor-urban/layers/<id>.geojson` so they survive a reload.
- Remembers the last workspace and re-opens it on next launch.

Without a workspace open, the app still works for ad-hoc exploration, but nothing persists.

## Map mode features

### Layers

- Click a `.geojson` file in the Files pane to load it as a styled vector layer.
- The **Layers** pane shows count, visibility toggle, zoom-to, and remove.
- AI-generated layers (from chat tool calls) appear here automatically.
- Layer styles (fill, line, opacity) can be edited from the chat by asking the assistant to `set_layer_style`.

### Basemaps

Seven free raster basemaps, switchable from the map UI:

- Street (OSM), Satellite (Esri World Imagery), Dark / Light (CartoDB), Terrain (OpenTopoMap), Topo (Esri), Humanitarian (OSM-HOT).

No API key is required for any of them.

### Bookmarks

Save the current map extent as a named bookmark. The assistant can also bookmark for you (`save_bookmark`) and fly to one (`go_to_bookmark`).

### Export

- **Map → PNG**: a snapshot of the current canvas.
- **Map → PDF**: A4 landscape with title and footer.
- **Layer → GeoJSON file**: per-layer download.
- **Region clip**: clip every loaded layer to either the current viewport or a named region/boundary, save as a single GeoJSON, and add it as a new layer.

### Zoning

The Zones panel shows a built-in legend (R1, R2, C1, I1, G, MX, INST). Load a GeoJSON whose features have a `zone_code` property and ask the assistant to `analyze_zones` (per-zone area, density) or `detect_zone_overlaps` (where two different zones cover the same ground).

## Document mode

Drop in or open a planning document:

- **Image formats** (PNG, JPG, JPEG, WEBP, GIF, BMP) — sent directly to the model.
- **PDF** — rasterized client-side with `pdfjs-dist` to a capped 2200-pixel-longer-axis PNG and sent as vision input. Multi-page navigation is supported.

The AI is given a planning-analyst persona and can identify land use, zoning areas, transportation networks, infrastructure, density patterns, boundaries, and labels. Document mode also bridges to the live map — the model can `fly_to`, drop markers, run `osm_search`, and save findings as artifacts even while you're chatting about a document.

## AI chat

The chat panel on the right is the primary control surface. You can:

- Have multiple conversations (left rail of the chat panel). Each is persisted into `project.json`.
- Ask the assistant to navigate (`fly to Chandigarh`), fetch data (`show all schools in Sector 22`), measure (`area of this polygon`), draw (`mark a 2 km buffer around the airport`), analyze (`compare residential and commercial zoning`), or document (`save these findings as an artifact`).
- See tool calls inline as they execute — every OSM query, GIS operation, or map action is visible in the conversation.

Streaming text uses a WebSocket; replies appear token-by-token.

### What the assistant can do

| Capability | Tools |
|---|---|
| **Navigate** | `fly_to`, `fit_bounds`, `go_to_bookmark` |
| **Annotate** | `add_marker`, `add_markers`, `clear_markers`, `draw_line`, `draw_polygon`, `draw_circle` |
| **Layers** | `add_geojson`, `toggle_layer`, `remove_layer`, `set_layer_style`, `highlight_features` |
| **Bookmarks** | `save_bookmark`, `go_to_bookmark`, `export_region_clip` |
| **OSM data** | `osm_search` (amenities, buildings, roads), `osm_boundary` (admin polygons), `osm_boundary_union` (merge multiple boundaries server-side), `osm_reverse_geocode`, `osm_route_overview` |
| **GIS analysis** | `gis_buffer`, `gis_centroid`, `gis_area`, `gis_convex_hull`, `gis_point_in_polygon`, `gis_bounding_box`, `gis_union` |
| **Zoning** | `analyze_zones`, `detect_zone_overlaps` |
| **Demographics** | `get_demographics` (population/place context around coordinates) |
| **Weather** | `get_weather`, `get_air_quality` |
| **Search & geocode** | `web_search`, `geocode`, `measure_distance`, `measure_area` |
| **Artifacts** | `create_artifact`, `list_artifacts`, `get_artifact` |

The current map state — viewport bounds, visible layers, geometry data for small layers, saved bookmarks — is appended to every prompt, so the assistant is always aware of what you're looking at.

## Artifacts

Long-form notes and analyses the assistant generates (or you ask it to save) live in a SQLite database and appear in the **Artifacts** panel: title, content, type, timestamps, plus full CRUD via the panel's HTTP API.

---

# Part 2 — For Developers

## Tech stack

| Layer | Stack |
|---|---|
| Desktop shell | Electron |
| Renderer | React 18 + Vite (electron-vite) + TypeScript |
| Map | MapLibre GL + Turf.js |
| Backend | Python 3.11+, FastAPI, uvicorn |
| LLM | OpenAI Chat Completions (streaming, tool calling) |
| Geo APIs | Overpass, Nominatim, OSRM, Open-Meteo (all free, keyless) |
| Geometry | Shapely (server), Turf.js (client) |
| Storage | SQLite (artifacts) + JSON files in workspace (project state) |
| Packaging | electron-builder + PyInstaller (frozen backend binary) |

## Top-level layout

```
.
├── apps/desktop/                  Electron + React frontend
│   ├── src/main/index.ts          Electron main: window, IPC, backend spawn
│   ├── src/preload/index.ts       contextBridge IPC surface
│   └── src/renderer/              React UI
│       ├── App.tsx                State container; map ↔ chat ↔ panels
│       ├── types.ts               MapAction union, basemaps, zone presets
│       └── components/            MapView, ChatPanel, FileTree, …
├── packages/backend/              Python FastAPI backend
│   ├── main.py                    App + CORS + router includes
│   ├── database.py                SQLite + migrations
│   ├── routers/
│   │   ├── chat.py                ★ Agentic loop, tool registry, action contract
│   │   ├── files.py               Workspace file listing
│   │   ├── artifacts.py           Artifact CRUD
│   │   ├── reports.py             Markdown report generation
│   │   └── geocode.py             Nominatim wrapper
│   ├── mcp_servers/               One class per domain (OSM, GIS, …)
│   └── tools/
│       ├── geo.py                 Spherical-shoelace area, helpers
│       └── utility.py             UtilityServer (search, geocode, artifacts)
├── ARCHITECTURE.md                This file
├── CLAUDE.md                      Orientation for AI coding agents
└── README.md                      Setup & build commands
```

## Process model

```
Electron main process (apps/desktop/src/main/index.ts)
  ├─ creates BrowserWindow → loads renderer
  ├─ exposes IPC (file dialogs, read dir, switch model) via preload
  └─ in production only: spawns the PyInstaller-frozen backend binary
                          (`Resources/backend/backend --port 8765`)

Renderer (Chromium) talks to:
  ├─ Backend  ws://localhost:8765/api/chat/ws    ← streaming chat & tool calls
  ├─ Backend  http://localhost:8765/api/*        ← files, artifacts, reports, geocode
  └─ Electron main via window.electronAPI       ← OS access only
```

In **dev mode** (`pnpm dev`), Electron does *not* spawn the backend — `pnpm dev:backend` runs uvicorn separately so you get hot reload on both sides.

## Three communication channels

| Channel | Endpoint / API | Purpose |
|---|---|---|
| **WebSocket** | `ws://localhost:8765/api/chat/ws` | Streaming chat tokens, tool-use events, action dispatch |
| **HTTP** | `/api/files`, `/api/artifacts`, `/api/reports`, `/api/geocode`, `/health` | CRUD, geocoding, Markdown reports |
| **Electron IPC** | `window.electronAPI.*` | Local OS only — file picker, read dir, base64-read for vision, last-workspace, model switch |

CORS is locked to loopback origins (`file://`, `app://`, `http(s)://localhost`, `127.0.0.1`, `[::1]`) — see `packages/backend/main.py:26`.

## The agentic loop

The heart of the AI behavior lives in `packages/backend/routers/chat.py:_run_agent`. For each user turn:

```
1. Send messages + tool defs to OpenAI (streaming).
2. As deltas arrive:
     - text deltas → forwarded to frontend as {"type": "stream", "content": …}
     - tool-call deltas → accumulated in tool_calls_acc keyed by index
3. When the stream ends, append the assistant message to history.
4. If the model called tools:
     a. Send {"type": "tool_use", "tool", "args"} per call.
     b. Execute each tool via _execute_tool (action OR MCP server).
     c. Append tool results back into history.
     d. Loop back to step 1.
5. Otherwise, break. Send {"type": "end"}.
```

A safety cap of `max_rounds = 10` prevents runaway loops. Tool-call argument JSON that gets cut off mid-stream is returned as a structured error so the next turn stays well-formed (every `tool_call_id` must have a matching tool message).

The connection holds a per-WebSocket message history. The renderer can also pass `history` on a turn to replay a prior conversation — this is how conversation switching and model switching work without losing context.

## The action contract

Some tools are **map actions** rather than data fetches. When the model calls one, the backend doesn't compute anything — it just forwards the call to the renderer:

```json
{ "type": "action", "action": "fly_to", "payload": { "lat": 30.7, "lng": 76.8, "zoom": 13 } }
```

The set lives in `_ACTION_TOOLS` (`routers/chat.py:63`):

```
fly_to · fit_bounds
add_marker · add_markers · clear_markers
draw_line · draw_polygon · draw_circle · add_geojson
highlight_features · set_layer_style · toggle_layer · remove_layer
save_bookmark · go_to_bookmark · export_region_clip
```

On the frontend, `App.tsx:handleMapAction` routes each action:

- **Layer mutations** (`add_geojson`, `toggle_layer`, `remove_layer`) → mutate the canonical `layers` React state directly so they appear in `mapContext` on the next turn.
- **AI markers** → merged into a single `"AI Markers"` Point layer (so they survive reload, show in `mapContext`, and persist to `project.json`).
- **AI-drawn shapes** (`draw_line`, `draw_polygon`, `draw_circle`) → promoted to real layers with `source: "ai_draw"` so the assistant can reference them next turn.
- **Bookmarks / region clip** → handled in React.
- **Everything else** → queued onto `mapActions[]`, consumed by `MapView.tsx`, drained via `onActionsProcessed`.

To add a new action you must touch all three of: backend tool def + dispatch (`chat.py`), `MapAction` union (`types.ts`), action switch (`MapView.tsx`). The `add-map-action` skill in `.claude/skills/` encodes the procedure.

## The MCP server pattern

Each domain server in `packages/backend/mcp_servers/` is a class with three things:

```python
class FooServer:
    description: str
    tool_names: set[str]                                # {"foo_x", "foo_y"}
    def get_declarations(self) -> list[ToolDeclaration]: ...
    async def execute(self, tool_name: str, args: dict) -> dict: ...
```

Servers live in `routers/chat.py:_servers` and their declarations are flattened into the OpenAI tool list by `_build_tools()`. There is **no external MCP stdio bridge** — the in-app chat is the only surface.

| Server | File | Tools |
|---|---|---|
| `OSMServer` | `osm_server.py` | `osm_search`, `osm_boundary`, `osm_boundary_union`, `osm_reverse_geocode`, `osm_route_overview` |
| `GISServer` | `gis_server.py` | `gis_buffer`, `gis_centroid`, `gis_area`, `gis_convex_hull`, `gis_point_in_polygon`, `gis_bounding_box`, `gis_union` |
| `WeatherServer` | `weather_server.py` | `get_weather`, `get_air_quality` |
| `ZoningServer` | `zoning_server.py` | `analyze_zones`, `detect_zone_overlaps` |
| `DemographicsServer` | `demographics_server.py` | `get_demographics` |
| `UtilityServer` | `tools/utility.py` | `web_search`, `geocode`, `measure_distance`, `measure_area`, `create_artifact`, `list_artifacts`, `get_artifact` |

Adding a domain tool means editing one server class — the flatten step picks it up automatically. Cross-cutting tools (search, geocode, artifacts) belong in `UtilityServer`. The `add-mcp-tool` skill in `.claude/skills/` encodes the procedure.

### Auto-display side effects

Some tools have post-execution side effects in `_execute_tool` so the model doesn't have to chain a second call:

- `osm_search` with results → auto-`add_geojson`. Only a summary (count + first 50 names/coords) goes back to the model.
- `osm_boundary` and `osm_boundary_union` → auto-`add_geojson`, plus the boundary's centroid, bbox, and (for unions) area breakdown go back to the model so it can chain `gis_buffer`, `gis_area`, etc.
- `osm_route_overview` → auto-`draw_line` with the route geometry.
- `gis_buffer`, `gis_convex_hull`, `gis_union` → auto-`add_geojson` of the result.
- `create_artifact` → fires a `refresh_artifacts` action so the panel re-fetches.

## Geospatial conventions

- **All coordinates are EPSG:4326 lat/lng.** No reprojection happens anywhere in this codebase.
- **Shapely operates on raw lat/lng**, so `.area` is in degree² (meaningless). The `gis_area` tool and `measure_area` use a homegrown spherical-shoelace approximation in `tools/geo.py`. Acceptable for small polygons; diverges from a true geodesic for large ones. Don't introduce code that assumes a projected CRS.
- **Tile sources are free raster XYZ.** No Mapbox token, no PMTiles, no MBTiles. Defined in `apps/desktop/src/renderer/types.ts:BASEMAPS`.
- **OSM data path:** Overpass API → ring-merge for ways → GeoJSON Feature. Boundary fetches additionally fall through to Nominatim with `polygon_geojson=1`.
- **Frontend geometry ops use Turf.js** (`@turf/turf`).

## Frontend state

Pure React `useState`/`useRef`. No Zustand, no Redux, no Context. All state lives in `App.tsx` and flows down as props:

```
App.tsx state:
  appMode               'map' | 'document'
  workspacePath         folder absolute path or null
  layers                GeoJSONLayer[]   ← canonical layer store
  mapViewState          { center, zoom, bearing, pitch }
  mapBounds             current viewport
  basemap               key into BASEMAPS
  conversations         Conversation[]   ← persisted in project.json
  bookmarks             MapBookmark[]
  mapActions            queue → drained by MapView
  artifactsRevision     bump to force ArtifactsPanel refresh
```

`MapView` exposes a ref (`MapViewHandle`) for canvas access (used for PNG/PDF export). `mapActions` is a queue array; `MapView` processes and clears via `onActionsProcessed`. **Don't add a state library** — match the existing pattern.

## Persistence

Three places state goes to disk:

| What | Where | Format |
|---|---|---|
| Project state (layers, map view, conversations, bookmarks, basemap) | `<workspace>/project.json` | JSON, debounced 800ms after any change, also flushed on app quit |
| Chat-generated layers | `<workspace>/.cursor-urban/layers/<id>.geojson` | Materialized when project saves |
| Last-opened workspace | `userData/last-workspace.json` (prod) or `.tmp/last-workspace.json` (dev) | Auto-restored on launch |
| Artifacts | SQLite at `packages/backend/cursor_urban.db` (override with `CURSOR_URBAN_DB`) | WAL-mode, simple migrations in `database.py` |
| Selected model | `packages/backend/model_config.json` | Read by both Electron and Python |

`project.json` stores layer file paths **relative to the workspace** so moving the workspace folder doesn't break it. Absolute paths from older projects keep working.

## HTTP API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/api/files?path=…` | List workspace files (path-restricted) |
| GET | `/api/geocode?query=…&limit=5` | Nominatim wrapper |
| GET | `/api/artifacts` · POST · GET `/{id}` · PUT · DELETE | Artifact CRUD |
| POST | `/api/reports/generate` | LLM-generated Markdown report |
| WS | `/api/chat/ws` | Chat + tool calls + map actions (the main loop) |

Every request is constrained to loopback origins by CORS.

## Electron IPC surface

Defined in `apps/desktop/src/preload/index.ts`. Renderer accesses these via `window.electronAPI.*`:

```
selectWorkspace()              → opens folder picker
readDirectory(dirPath)         → list directory entries
readFile(path) / writeFile     → text I/O
readFileBase64(path)           → for PDF rasterization & vision
openFile({filters})            → file picker with extension filter
getLastWorkspace / setLastWorkspace
getModels / getCurrentModel / switchModel
onAppBeforeQuit(handler)       → flush project save before quit
```

## Run

```bash
pnpm install                            # once
cd packages/backend && python -m venv .buildenv \
  && source .buildenv/bin/activate \
  && pip install -r requirements.txt    # once
export OPENAI_API_KEY=...

pnpm dev                                # backend (uvicorn :8765) + renderer
```

## Build for distribution

```bash
# 1. Freeze the Python backend
cd packages/backend
source .buildenv/bin/activate
pip install pyinstaller
pyinstaller backend.spec --noconfirm

# 2. Package the Electron app
cd apps/desktop
npx electron-vite build
npx electron-builder
# → apps/desktop/release/
```

In production, `apps/desktop/src/main/index.ts:startBackend` spawns the PyInstaller binary at `Resources/backend/backend`.

## Where to read first (in order)

1. `packages/backend/routers/chat.py` — agentic loop, action contract, tool registry. **The heart of the AI behavior.**
2. `apps/desktop/src/renderer/App.tsx` — single state container, component wiring, conversation persistence.
3. `apps/desktop/src/renderer/components/MapView.tsx` — MapLibre setup + action handlers.
4. `apps/desktop/src/renderer/components/ChatPanel.tsx` — WebSocket client, streaming render.
5. `packages/backend/mcp_servers/osm_server.py` — canonical MCP server example with the most logic.
6. `apps/desktop/src/renderer/types.ts` — shared interfaces, basemap defs, zone presets, layer colors, the `MapAction` union.
7. `apps/desktop/src/preload/index.ts` — full IPC surface between renderer and Electron main.

## Known gaps

- **No tests.** Anywhere. The agent loop, OSM ring-merge, and area math are entirely untested.
- **Spherical-shoelace area** diverges from a true geodesic measurement on large polygons (continent-scale). Fine for cities and regions.
- **Single-model UI.** Model picker is wired through but the dropdown currently lists one OpenAI model; the abstraction in `llm/base.py` is ahead of the UI.
- **No PMTiles / MBTiles / vector tile support.** All basemaps are external raster XYZ.
