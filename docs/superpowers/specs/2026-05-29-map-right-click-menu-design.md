# Map Right-Click Context Menu — Design Spec

**Date:** 2026-05-29
**Status:** Approved (pending implementation)

## Goal

Add a right-click context menu to the MapLibre map with three actions:

1. **📍 Add marker here** — drop a pin at the clicked location, labeled with its reverse-geocoded address.
2. **🛣 Street View** — open a large dialog showing an interactive 360° Street View panorama for the location.
3. **💬 Ask chat about this place** — auto-send a templated prompt to the AI chat so it gathers everything it can about the location using existing tools.

## Non-Goals

- No new state-management library (repo uses plain `useState`/`useRef` in `App.tsx`; match it).
- No persistence of the Street View dialog or chat prompt (ephemeral by design).
- No automated test suite (repo has none; quality bar is "golden paths work, don't crash the chat → tool → map flow"). Verification is manual via running the app.

## User-Facing Behavior

Right-clicking anywhere on the map opens a small menu at the cursor with the three items above. The menu closes on: item click, left-click elsewhere, `Escape`, or map move.

- **Add marker** places the pin immediately with a coordinate label (`"12.9716, 77.5946"`), then updates the label to the resolved address (`"MG Road, Bengaluru"`) when reverse-geocoding returns. A slow or failed geocode never blocks the pin.
- **Street View** opens a full-screen modal. While the panorama downloads, a spinner shows. If there is no Street View coverage near the click, the dialog shows a friendly "No Street View imagery here." empty state. The panorama is navigable (drag to look around) via an embedded 360° viewer. Header shows the address and capture date.
- **Ask chat** switches the right panel to the Chat tab and auto-sends a templated prompt. If no conversation is active, one is created first, then the prompt is sent.

## Architecture

### Frontend

#### `MapView.tsx` — context menu

- Add a `contextmenu` listener in the existing map-init `useEffect`. MapLibre's event provides `{lngLat, point}`.
- Render a small absolutely-positioned menu at `point` via local `useState` (`menuPos: {x, y} | null` plus the target `{lng, lat}`).
- Close the menu on item click, document left-click, `Escape` keydown, and map `move`/`movestart`.
- Add three optional callback props; MapView stays "dumb" and delegates orchestration to `App.tsx`:
  - `onAddMarker(lng: number, lat: number)`
  - `onOpenStreetView(lng: number, lat: number)`
  - `onAskChat(lng: number, lat: number)`
- Styles for the menu live in `MapView.css`.

#### `StreetViewDialog.tsx` — new component

- Full-screen modal overlay. Props: `target: {lng, lat} | null`, `onClose()`.
- On open (target set), fetch `GET /api/streetview/meta?lat=&lng=`.
  - `{found: false}` → render empty state.
  - `{found: true, pano_id, address, date, ...}` → initialize the 360° viewer.
- 360° viewer: use **`pannellum`** (lightweight, MIT, canvas-based, no React wrapper). Initialize on a div ref with an `equirectangular` panorama pointed at `GET /api/streetview/pano?pano_id=<id>&zoom=3`.
- Header shows 📍 address + capture date. Close via `[X]`, `Escape`, or backdrop click.
- Loading spinner while the (multi-MB) panorama downloads. Error state (with retry) if `/pano` fails.
- Styles in an adjacent CSS file (e.g. `StreetViewDialog.css`).

#### `ChatPanel.tsx` — external message injection

- Add prop `injectedMessage: { text: string; nonce: number } | null`.
- A `useEffect` keyed on `injectedMessage?.nonce` calls the existing `sendMessageDirect(text)`. The `nonce` (monotonic counter) lets the same coordinates be asked twice in a row.
- Reuse the existing `pendingInputRef` mechanism for the "send after a freshly-created conversation exists" case (already implemented for the suggestion-chip flow).

#### `App.tsx` — orchestration

- Supplies the three MapView callbacks:
  - `onAddMarker` → reverse-geocode (non-blocking) then `appendMarkersToLayer([{lng, lat, label}])` (existing function; pins flow into the persistent "AI Markers" layer and `project.json`).
  - `onAskChat` → set `activeRightTab = 'chat'`; if no active conversation, create one; then set `injectedMessage = {text: <template>, nonce: ++counter}`.
  - `onOpenStreetView` → set `streetViewTarget = {lng, lat}` (opens the dialog).
- Holds `streetViewTarget` state and renders `<StreetViewDialog target={streetViewTarget} onClose={() => setStreetViewTarget(null)} />`.
- Holds the `injectedMessage` state passed to `ChatPanel`.

**Ask-chat template:**
> "Tell me everything you can about this location (`<lat>`, `<lng>`): the address/neighborhood, nearby amenities, demographics, weather, and any notable features. Use your tools."

### Backend

#### `routers/streetview.py` — new router, mounted at `/api/streetview` in `main.py`

- `GET /api/streetview/meta?lat=&lng=&radius=50`
  - Runs `streetlevel.streetview.find_panorama(lat, lng, radius=50)` in a threadpool (`run_in_threadpool` — the lib is synchronous).
  - Returns `{found: true, pano_id, lat, lon, date, heading, address}` or `{found: false}`.
- `GET /api/streetview/pano?pano_id=&zoom=3`
  - `find_panorama_by_id(pano_id)` then `get_panorama(pano, zoom)` (both in a threadpool) → equirectangular PIL image.
  - Encode to JPEG and return `Response(content=..., media_type="image/jpeg")`.
  - Default `zoom=3` (quality vs. download-time balance; lib supports 0–5).

`streetlevel` is keyless — it scrapes Google's public Street View tile endpoint. No `GOOGLE_MAPS_API_KEY` required.

#### `routers/geocode.py` — add reverse mode

- New endpoint `GET /api/geocode/reverse?lat=&lng=`.
- Mirrors the existing forward-geocode tiering: Google reverse geocoding when `GOOGLE_MAPS_API_KEY` is set, else Nominatim `/reverse` (the server-side proxy exists because browsers can't set the required `User-Agent`).
- Returns `{display_name, lat, lon, type, class}` (stable shape, matching the forward endpoint's convention).

## Dependencies

- **Backend:** add `streetlevel` to `packages/backend/requirements.txt`. Pure-Python (no compiled extensions); depends on `Pillow` (already present) and an HTTP client. **PyInstaller (prod build):** verify `streetlevel` and its transitive deps are collected — add a hidden-import / `--collect-all streetlevel` entry to the spec if the frozen binary fails to import it.
- **Frontend:** add `pannellum` to `apps/desktop/package.json`.

(Per project memory: new dependencies are permitted when they improve the app; flagged here with what/why and the PyInstaller consideration.)

## Error Handling

| Failure | Behavior |
|---|---|
| No Street View coverage near click | `/meta` → `{found: false}` → dialog empty state. No crash. |
| `streetlevel` throws (expired pano ID, Google block) | Backend returns clean JSON error / 502; dialog shows retryable error state. |
| Reverse-geocode fails or is slow | Marker keeps its coordinate label; pin is never blocked. |
| Ask-chat WS / API-key error | Existing `ChatPanel` error banner handles it; no new path. |

## Persistence

- Right-click markers use the existing "AI Markers" layer → already saved to `project.json` and restored on reload.
- Street View dialog state and the injected chat prompt are ephemeral (nothing to persist).

## Files Touched

| File | Change |
|---|---|
| `packages/backend/routers/streetview.py` | **new** — `/meta` + `/pano` |
| `packages/backend/main.py` | register streetview router |
| `packages/backend/requirements.txt` | add `streetlevel` |
| `packages/backend/routers/geocode.py` | add `/reverse` endpoint |
| `apps/desktop/src/renderer/components/MapView.tsx` | contextmenu listener + menu UI + 3 callback props |
| `apps/desktop/src/renderer/components/MapView.css` | context-menu styles |
| `apps/desktop/src/renderer/components/StreetViewDialog.tsx` | **new** |
| `apps/desktop/src/renderer/components/StreetViewDialog.css` | **new** — modal styles |
| `apps/desktop/src/renderer/App.tsx` | wire 3 actions, dialog state, chat injection |
| `apps/desktop/src/renderer/components/ChatPanel.tsx` | `injectedMessage` prop |
| `apps/desktop/package.json` | add `pannellum` |

## Verification (manual)

Run the app (`pnpm dev`) and exercise each menu item:

1. Right-click → menu appears at cursor; closes on Escape / outside-click / map move.
2. **Add marker** → pin appears immediately (coords label), then label updates to address. Survives reload.
3. **Street View** → dialog opens; navigable 360° pano loads; header shows address + date. Right-click over open water / no-coverage → empty state.
4. **Ask chat** → Chat tab activates, prompt auto-sends, AI responds using tools. Works with no prior conversation (creates one).
