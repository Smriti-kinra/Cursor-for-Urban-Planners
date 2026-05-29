# Cursor for Urban Planners

A geospatial-first, AI-driven desktop IDE for urban planners. You chat with an LLM that drives a live MapLibre map — flying to places, fetching OpenStreetMap features, drafting zoning, running GIS analysis, pulling demographics and weather, opening 360° Street View, and saving planning artifacts. Built as an Electron desktop app over a Python FastAPI backend.

> Think "Cursor, but the canvas is a map and the agent's tools are geospatial."

---

## Highlights

- **Agentic chat over a live map** — natural-language requests turn into real map actions (fly, draw, mark, style layers) and data fetches, streamed token-by-token with every tool call visible inline.
- **Rich geospatial toolset** — OpenStreetMap (Overpass/Nominatim), Overture Maps, GIS geometry ops (buffer, hull, union, area), zoning analysis, demographics, weather & air quality.
- **Optional Google Maps Platform** — Places autocomplete/details/nearby/density, elevation, air quality, solar potential, and 360° Street View (gracefully degrades when no key is set).
- **Document analysis mode** — drop in a planning PDF or map image and have the AI read land use, zoning, transport networks, and labels via vision.
- **Workspace persistence** — open a folder and your layers, map view, conversations, bookmarks, and basemap auto-save to `project.json`.
- **Offline-friendly basemaps** — seven free raster basemaps, no API token required for the core experience.

---

## Features

### 🗺️ Map mode (the primary surface)

| Feature | What it does |
|---|---|
| **Layers** | Click a `.geojson` in the Files pane to load it as a styled vector layer. The Layers pane gives count, visibility toggle, zoom-to, and remove. AI-generated layers appear here automatically. |
| **Basemaps** | Seven free raster basemaps — Street (OSM), Satellite (Esri), Dark/Light (CartoDB), Terrain (OpenTopoMap), Topo (Esri), Humanitarian (OSM-HOT). No API key needed. |
| **Bookmarks** | Save the current extent as a named bookmark; the assistant can save and fly to bookmarks too. |
| **Export** | Map → PNG snapshot, Map → A4 landscape PDF, per-layer GeoJSON download, and **region clip** (clip all layers to the viewport or a named boundary and save as one GeoJSON layer). |
| **Zoning** | Built-in legend (R1, R2, C1, I1, G, MX, INST). Load a GeoJSON with a `zone_code` property and ask the assistant to analyze per-zone area/density or detect overlapping zones. |
| **Street View** | Right-click anywhere on the map to drop a pin and open an embedded 360° panorama (powered by Google Street View + pannellum). |

### 📄 Document mode

Drop in or open a planning document for AI analysis:

- **Images** (PNG, JPG, JPEG, WEBP, GIF, BMP) — sent directly to the model's vision input.
- **PDF** — rasterized client-side with `pdfjs-dist` (capped at 2200px on the long axis) and sent as vision input, with multi-page navigation.

The AI takes on a planning-analyst persona and can identify land use, zoning areas, transportation networks, infrastructure, density patterns, boundaries, and labels. Document mode still bridges to the live map — the assistant can fly, drop markers, run OSM searches, and save artifacts while you discuss a document.

### 🤖 AI chat assistant

The chat panel on the right is the main control surface:

- **Multiple conversations** — each persisted into `project.json`.
- **Natural-language commands** — navigate (*"fly to Chandigarh"*), fetch (*"show all schools in Sector 22"*), measure (*"area of this polygon"*), draw (*"mark a 2 km buffer around the airport"*), analyze (*"compare residential and commercial zoning"*), or document (*"save these findings as an artifact"*).
- **Visible tool calls** — every OSM query, GIS op, or map action shows inline as it executes.
- **Streaming** — replies arrive token-by-token over a WebSocket.
- **Map-aware context** — the current viewport bounds, visible layers, small-layer geometry, and saved bookmarks are appended to every prompt, so the assistant always knows what you're looking at.

#### What the assistant can do

| Capability | Tools |
|---|---|
| **Navigate** | `fly_to`, `fit_bounds`, `go_to_bookmark` |
| **Annotate** | `add_marker`, `add_markers`, `clear_markers`, `draw_line`, `draw_polygon`, `draw_circle` |
| **Layers** | `add_geojson`, `toggle_layer`, `remove_layer`, `set_layer_style`, `highlight_features` |
| **Bookmarks & clip** | `save_bookmark`, `go_to_bookmark`, `export_region_clip` |
| **OpenStreetMap** | `osm_search`, `osm_boundary`, `osm_boundary_union`, `osm_reverse_geocode`, `osm_route_overview` |
| **Overture Maps** | `overture_places_search`, `overture_buildings_search` |
| **GIS analysis** | `gis_buffer`, `gis_centroid`, `gis_area`, `gis_convex_hull`, `gis_point_in_polygon`, `gis_bounding_box`, `gis_union` |
| **Zoning** | `analyze_zones`, `detect_zone_overlaps` |
| **Demographics** | `get_demographics` (population/place context around coordinates) |
| **Weather** | `get_weather`, `get_air_quality` |
| **Google Places** *(needs key)* | `places_autocomplete`, `place_details`, `nearby_places`, `nearby_places_in_polygon`, `places_density` |
| **Google environment** *(needs key)* | `get_elevation`, `get_air_quality_google`, `get_solar_building` |
| **Search & geocode** | `web_search`, `geocode`, `measure_distance`, `measure_area` |
| **Artifacts** | `create_artifact`, `list_artifacts`, `get_artifact` |

### 📌 Artifacts

Long-form notes and analyses the assistant generates (or that you ask it to save) live in a local SQLite database and appear in the **Artifacts** panel with full CRUD — title, content, type, and timestamps.

### 💾 Workspace & persistence

Open a folder via the title-bar button and the app:

- Lists `.geojson` (and other) files in the **Files** pane.
- Auto-saves a `project.json` containing map state, layers, conversations, bookmarks, and basemap (debounced, also flushed on quit).
- Materializes chat-generated layers into `<workspace>/.cursor-urban/layers/<id>.geojson` so they survive reloads.
- Remembers the last workspace and re-opens it on next launch.

Without a workspace open, the app still works for ad-hoc exploration — nothing persists.

---

## Prerequisites

- **Node.js** ≥ 18
- **pnpm** ≥ 8
- **Python** ≥ 3.11

## Setup

### 1. Install frontend dependencies

```bash
pnpm install
```

### 2. Create a Python virtual environment and install backend dependencies

```bash
cd packages/backend
python -m venv .buildenv
source .buildenv/bin/activate   # Windows: .buildenv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | ✅ Yes | Powers the chat assistant (OpenAI Chat Completions, streaming + tool calls). |
| `OPENAI_MODEL` | No | Override the default model (`gpt-4o-mini`). |
| `GOOGLE_MAPS_API_KEY` | No | Enables Google Places, environment (elevation/air quality/solar), and Street View. The app runs without it — those tools simply report as unavailable. |
| `CURSOR_URBAN_DB` | No | Override the SQLite artifacts DB path (defaults to `packages/backend/cursor_urban.db`). |

```bash
export OPENAI_API_KEY=sk-...
export GOOGLE_MAPS_API_KEY=...   # optional
```

Everything else — Overpass, Nominatim, OSRM, Open-Meteo, Overture, DuckDuckGo search — is free and keyless.

## Development

Start the backend and Electron app together:

```bash
pnpm dev
```

Or run them separately:

```bash
# Terminal 1 — backend (uvicorn, hot reload)
cd packages/backend
source .buildenv/bin/activate
python -m uvicorn main:app --reload --port 8765

# Terminal 2 — desktop (electron-vite, hot reload)
cd apps/desktop
npx electron-vite dev
```

> In dev mode, Electron does **not** spawn the backend — `pnpm dev:backend` runs uvicorn separately so both sides hot-reload independently.

## Build for distribution

### 1. Freeze the Python backend (PyInstaller)

```bash
cd packages/backend
source .buildenv/bin/activate
pip install pyinstaller
pyinstaller backend.spec --noconfirm
```

### 2. Package the Electron app

```bash
cd apps/desktop
npx electron-vite build
npx electron-builder
```

Output is written to `apps/desktop/release/`. In production, Electron spawns the frozen backend binary from `Resources/backend/backend`.

The root `package.json` also wraps these:

```bash
pnpm build          # build the desktop renderer
pnpm build:backend  # freeze the Python backend
pnpm package        # backend + electron-builder, end to end
```

---

## Architecture at a glance

```
Electron main (apps/desktop/src/main/index.ts)
  ├─ spawns the FastAPI backend on :8765 (PyInstaller-frozen in prod, uvicorn in dev)
  └─ creates a BrowserWindow → loads the React renderer

Renderer (apps/desktop/src/renderer/) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws   ← streaming chat + tool calls + map actions
  ├─ Backend over HTTP       /api/files /api/artifacts /api/reports /api/geocode /api/streetview
  └─ Electron main over IPC  (file dialogs, read directory, persist last-workspace, switch model)

Backend (packages/backend/) talks to:
  └─ OpenAI HTTPS (key from OPENAI_API_KEY)
     + Overpass, Nominatim, OSRM, Open-Meteo, Overture, DuckDuckGo  (free, keyless)
     + Google Maps Platform  (optional, key from GOOGLE_MAPS_API_KEY)
```

### Three communication channels

| Channel | Used for |
|---|---|
| **WebSocket** (renderer ↔ backend) | Streaming chat, tool calls, and map actions. |
| **HTTP** (renderer ↔ backend) | List workspace files, CRUD on artifacts, Markdown reports, geocoding, Street View panoramas. |
| **Electron IPC** (renderer ↔ main) | Local OS only — file picker, read directory, base64 file read for vision, last-workspace, model switch. |

### Tech stack

| Layer | Stack |
|---|---|
| Desktop shell | Electron |
| Renderer | React 18 + Vite (electron-vite) + TypeScript |
| Map | MapLibre GL + Turf.js + pannellum (Street View) |
| Backend | Python 3.11+, FastAPI, uvicorn |
| LLM | OpenAI Chat Completions (streaming, tool calling) |
| Geo APIs | Overpass, Nominatim, OSRM, Open-Meteo, Overture, Google Maps Platform |
| Geometry | Shapely (server), Turf.js (client) |
| Storage | SQLite (artifacts) + JSON files in the workspace (project state) |
| Packaging | electron-builder + PyInstaller (frozen backend binary) |

> **Coordinates everywhere are EPSG:4326 lat/lng** — no reprojection is performed. Area math uses a spherical-shoelace approximation (fine for cities and regions; diverges from a true geodesic at continent scale).

## Project structure

```
.
├── apps/desktop/                  Electron + React frontend
│   ├── src/main/index.ts          Electron main: window, IPC, backend spawn
│   ├── src/preload/index.ts       contextBridge IPC surface
│   └── src/renderer/              React UI
│       ├── App.tsx                Single state container; map ↔ chat ↔ panels
│       ├── types.ts               MapAction union, basemaps, zone presets
│       └── components/            MapView, ChatPanel, FileTree, StreetViewDialog, …
├── packages/backend/              Python FastAPI backend
│   ├── main.py                    App + CORS + router includes
│   ├── database.py                SQLite + migrations
│   ├── routers/                   chat, files, artifacts, reports, geocode, streetview
│   ├── mcp_servers/               One class per domain (OSM, GIS, weather, zoning,
│   │                              demographics, Overture, Google Places, Google env)
│   └── tools/                     UtilityServer, geo helpers, Google/HTTP wrappers, cache
├── ARCHITECTURE.md                Deep dive — features + system wiring
├── CLAUDE.md                      Orientation for AI coding agents
└── README.md                      This file
```

For a deeper dive into the agentic loop, the action contract, the MCP server pattern, and persistence, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Known gaps

- **No automated tests** — the agent loop, OSM ring-merge, and area math are untested.
- **PDF vision is rasterize-then-send** — large multi-page PDFs are capped per page.
- **Spherical-shoelace area** diverges from a true geodesic on very large polygons.
- **Raster basemaps only** — no Mapbox token, PMTiles, MBTiles, or vector tiles.
```