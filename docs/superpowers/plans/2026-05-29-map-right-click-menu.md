# Map Right-Click Context Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a right-click context menu to the map with three actions — add a reverse-geocoded marker, open a 360° Street View dialog, and ask the AI chat about the clicked location.

**Architecture:** Backend gains a keyless Street View router (`streetlevel` → equirectangular JPEG) and a reverse-geocode endpoint. Frontend adds a context menu in `MapView.tsx` that delegates to three `App.tsx` callbacks, a `StreetViewDialog.tsx` modal using `pannellum` for 360° navigation, and a one-shot message-injection prop on `ChatPanel.tsx`. State stays in plain `useState`/`useRef` per repo convention; markers reuse the existing persistent "AI Markers" layer.

**Tech Stack:** FastAPI, `streetlevel` (Python, keyless), Pillow; React + MapLibre GL, `pannellum` (360° viewer), Turf.js.

> **Testing note:** This repo has no automated test suite and its quality bar is "golden paths work, don't crash" with manual verification (see `CLAUDE.md`). Per repo convention, tasks below use **manual verification** (curl / run-the-app / observe) instead of a test framework. Each task ends with concrete verify steps and a commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `packages/backend/routers/streetview.py` | **New.** `/meta` (find panorama near lat/lng) + `/pano` (download equirectangular JPEG). |
| `packages/backend/main.py` | Register the streetview router under `/api/streetview`. |
| `packages/backend/requirements.txt` | Add `streetlevel`. |
| `packages/backend/routers/geocode.py` | Add `GET /reverse` (coords → address). |
| `apps/desktop/package.json` | Add `pannellum` dependency. |
| `apps/desktop/src/renderer/components/MapView.tsx` | `contextmenu` listener + menu UI + three callback props. |
| `apps/desktop/src/renderer/components/MapView.css` | Context-menu styles. |
| `apps/desktop/src/renderer/components/StreetViewDialog.tsx` | **New.** Modal: fetch `/meta`, render pannellum or empty/error state. |
| `apps/desktop/src/renderer/components/StreetViewDialog.css` | **New.** Modal styles. |
| `apps/desktop/src/renderer/components/ChatPanel.tsx` | `injectedMessage` prop → one-shot `sendMessageDirect`. |
| `apps/desktop/src/renderer/App.tsx` | Wire three actions, dialog state, chat injection, reverse-geocode. |
| `apps/desktop/src/renderer/types.ts` | (If needed) shared types for injected message / street view target. |

---

## Task 1: Backend — Street View router

**Files:**
- Create: `packages/backend/routers/streetview.py`
- Modify: `packages/backend/main.py` (imports + `include_router`)
- Modify: `packages/backend/requirements.txt`

- [ ] **Step 1: Add the dependency**

Append to `packages/backend/requirements.txt`:

```
streetlevel>=0.10,<1
```

- [ ] **Step 2: Install it into the dev venv**

Run:
```bash
cd packages/backend && source .buildenv/bin/activate && pip install "streetlevel>=0.10,<1"
```
Expected: installs `streetlevel` plus its deps (`aiohttp`, `requests`, `numpy`, etc.). If the pinned range fails to resolve, run `pip install streetlevel` unpinned, then pin `requirements.txt` to the installed version (`pip show streetlevel | grep Version`).

- [ ] **Step 3: Verify the library works against a known-covered point**

Run (Times Square — reliably has coverage):
```bash
cd packages/backend && source .buildenv/bin/activate && python -c "
from streetlevel import streetview
p = streetview.find_panorama(40.7580, -73.9855, radius=50)
print('found:', p is not None)
if p: print(p.id, p.lat, p.lon, p.date)
"
```
Expected: `found: True` and a pano id / coords / date printed. If this fails with a network error, note it — the feature depends on Google's public endpoint being reachable.

- [ ] **Step 4: Create the router**

Create `packages/backend/routers/streetview.py`:

```python
"""Street View imagery via the keyless ``streetlevel`` library.

``streetlevel`` scrapes Google's public Street View tile endpoint — no
``GOOGLE_MAPS_API_KEY`` required. Its calls are synchronous, so we run them
in a threadpool to avoid blocking the event loop.

Two endpoints:
- ``GET /meta``  — find the nearest panorama to a point (metadata only).
- ``GET /pano``  — download a panorama by id as an equirectangular JPEG.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from streetlevel import streetview

router = APIRouter()


def _address_str(pano) -> str | None:
    addr = getattr(pano, "address", None)
    if not addr:
        return None
    try:
        # address is a list of LocalizedString with a .value attribute.
        parts = [getattr(a, "value", str(a)) for a in addr]
        return ", ".join(p for p in parts if p) or None
    except Exception:
        return None


@router.get("/meta")
async def streetview_meta(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: int = Query(50, ge=1, le=500),
):
    try:
        pano = await run_in_threadpool(
            streetview.find_panorama, lat, lng, radius=radius
        )
    except Exception as e:  # network / upstream change
        return JSONResponse(
            status_code=502,
            content={"found": False, "error": f"Street View lookup failed: {e}"},
        )

    if pano is None:
        return {"found": False}

    return {
        "found": True,
        "pano_id": pano.id,
        "lat": pano.lat,
        "lon": pano.lon,
        "date": str(pano.date) if getattr(pano, "date", None) else None,
        "heading": getattr(pano, "heading", None),
        "address": _address_str(pano),
    }


@router.get("/pano")
async def streetview_pano(
    pano_id: str = Query(...),
    zoom: int = Query(3, ge=0, le=5),
):
    try:
        pano = await run_in_threadpool(streetview.find_panorama_by_id, pano_id)
        if pano is None:
            return JSONResponse(status_code=404, content={"error": "Panorama not found."})
        image = await run_in_threadpool(streetview.get_panorama, pano, zoom)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Panorama download failed: {e}"},
        )

    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    return Response(content=buf.getvalue(), media_type="image/jpeg")
```

- [ ] **Step 5: Register the router**

In `packages/backend/main.py`, add `streetview` to the routers import on line 11:

```python
from routers import files, chat, artifacts, reports, geocode, streetview
```

And add after the geocode registration (line 42):

```python
app.include_router(streetview.router, prefix="/api/streetview", tags=["streetview"])
```

- [ ] **Step 6: Verify the endpoints (start the backend, curl both)**

Run the backend if not already running:
```bash
cd packages/backend && source .buildenv/bin/activate && uvicorn main:app --port 8765 &
```

Test `/meta`:
```bash
curl -s "http://localhost:8765/api/streetview/meta?lat=40.7580&lng=-73.9855" | head -c 400
```
Expected: JSON with `"found": true`, a `pano_id`, and a `date`.

Test `/pano` (use the pano_id from the previous response):
```bash
curl -s "http://localhost:8765/api/streetview/pano?pano_id=<PANO_ID>&zoom=2" -o /tmp/pano.jpg && file /tmp/pano.jpg
```
Expected: `/tmp/pano.jpg: JPEG image data, ...`. Open it to confirm it's a wide panorama.

Test no-coverage path (middle of the ocean):
```bash
curl -s "http://localhost:8765/api/streetview/meta?lat=0&lng=-40" | head -c 200
```
Expected: `{"found": false}`.

- [ ] **Step 7: Commit**

```bash
git add packages/backend/routers/streetview.py packages/backend/main.py packages/backend/requirements.txt
git commit -m "feat(streetview): add keyless Street View meta + pano endpoints"
```

---

## Task 2: Backend — reverse-geocode endpoint

**Files:**
- Modify: `packages/backend/routers/geocode.py`

- [ ] **Step 1: Inspect the existing forward endpoint**

Read `packages/backend/routers/geocode.py`. Note: it imports `google_geocode_query`, `has_google_key`, `GoogleUnavailable` from `tools.google`, and `http_client` from `tools.http`. The forward `geocode()` returns `{"results": [...]}`. The reverse endpoint will return a single `{...}` object (or `{"error": ...}`).

- [ ] **Step 2: Add the reverse endpoint**

Append to `packages/backend/routers/geocode.py` (after the existing `geocode` function):

```python
@router.get("/reverse")
async def reverse_geocode(lat: float = Query(...), lng: float = Query(...)):
    """Resolve coordinates to a human address. Nominatim ``/reverse``; the
    server-side proxy exists because browsers cannot set the ``User-Agent``
    that OSM's usage policy requires. (Google reverse is not wired here yet —
    Nominatim is sufficient for a marker label and always keyless.)"""
    try:
        data = await http_client.fetch_json(
            "https://nominatim.openstreetmap.org/reverse",
            namespace="nominatim",
            params={
                "lat": lat,
                "lon": lng,
                "format": "json",
                "addressdetails": 1,
                "zoom": 18,
            },
        )
        if not isinstance(data, dict) or "display_name" not in data:
            return {"display_name": None, "lat": lat, "lon": lng}
        return {
            "display_name": data.get("display_name"),
            "lat": float(data["lat"]) if data.get("lat") else lat,
            "lon": float(data["lon"]) if data.get("lon") else lng,
            "type": data.get("type"),
            "class": data.get("category") or data.get("class"),
        }
    except http_client.HTTPError as e:
        return {"error": str(e), "display_name": None, "lat": lat, "lon": lng}
    except Exception as e:
        return {"error": f"Unexpected error: {e}", "display_name": None, "lat": lat, "lon": lng}
```

> Note: the existing file imports `Query` from `fastapi` already (it's used by the forward endpoint). No new import needed. Confirm `from fastapi import APIRouter, Query` is at the top.

- [ ] **Step 3: Verify**

```bash
curl -s "http://localhost:8765/api/geocode/reverse?lat=40.7580&lng=-73.9855" | head -c 300
```
Expected: JSON with a `display_name` like `"... Manhattan, New York County, ..."`.

- [ ] **Step 4: Commit**

```bash
git add packages/backend/routers/geocode.py
git commit -m "feat(geocode): add reverse-geocode endpoint for marker labels"
```

---

## Task 3: Frontend — context menu in MapView

**Files:**
- Modify: `apps/desktop/src/renderer/components/MapView.tsx`
- Modify: `apps/desktop/src/renderer/components/MapView.css`

- [ ] **Step 1: Add the three optional props to `MapViewProps`**

In `MapView.tsx`, add to the `MapViewProps` interface (after `onLayerStyleChange`):

```typescript
  onAddMarker?: (lng: number, lat: number) => void
  onOpenStreetView?: (lng: number, lat: number) => void
  onAskChat?: (lng: number, lat: number) => void
```

Add them to the destructured params in the `MapView` function signature:

```typescript
    onLayerStyleChange,
    onAddMarker,
    onOpenStreetView,
    onAskChat,
```

- [ ] **Step 2: Add refs + state for the menu**

Near the other `useRef`s (after `onLayerStyleChangeRef`):

```typescript
  const onAddMarkerRef = useRef(onAddMarker)
  onAddMarkerRef.current = onAddMarker
  const onOpenStreetViewRef = useRef(onOpenStreetView)
  onOpenStreetViewRef.current = onOpenStreetView
  const onAskChatRef = useRef(onAskChat)
  onAskChatRef.current = onAskChat
```

Near the other `useState`s (after `showBasemaps`):

```typescript
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; lng: number; lat: number } | null>(null)
```

- [ ] **Step 3: Wire the `contextmenu` listener in the map-init effect**

Inside the init `useEffect`, after the `map.on('moveend', ...)` block and before `mapRef.current = map`, add:

```typescript
    map.on('contextmenu', (e) => {
      e.preventDefault?.()
      setCtxMenu({ x: e.point.x, y: e.point.y, lng: e.lngLat.lng, lat: e.lngLat.lat })
    })
    map.on('movestart', () => setCtxMenu(null))
```

- [ ] **Step 4: Close the menu on Escape / outside click**

Add a new `useEffect` (after the actions effect):

```typescript
  useEffect(() => {
    if (!ctxMenu) return
    const close = () => setCtxMenu(null)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setCtxMenu(null) }
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', onKey)
    }
  }, [ctxMenu])
```

- [ ] **Step 5: Render the menu**

In the returned JSX, after the basemap-switcher block (before the closing `</div>` of `.map-view`):

```tsx
      {ctxMenu && (
        <div
          className="map-context-menu"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className="ctx-item"
            onClick={() => { onAddMarkerRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
          >
            📍 Add marker here
          </button>
          <button
            className="ctx-item"
            onClick={() => { onOpenStreetViewRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
          >
            🛣 Street View
          </button>
          <button
            className="ctx-item"
            onClick={() => { onAskChatRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
          >
            💬 Ask chat about this place
          </button>
        </div>
      )}
```

- [ ] **Step 6: Add styles**

Append to `apps/desktop/src/renderer/components/MapView.css`:

```css
.map-context-menu {
  position: absolute;
  z-index: 1000;
  min-width: 200px;
  background: #1e1e1e;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  overflow: hidden;
  padding: 4px;
}
.map-context-menu .ctx-item {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  color: #e0e0e0;
  padding: 8px 10px;
  font-size: 13px;
  border-radius: 4px;
  cursor: pointer;
}
.map-context-menu .ctx-item:hover {
  background: #2d6cdf;
  color: #fff;
}
```

> Match existing color values in `MapView.css` if the theme differs — open the file first and reuse its palette/variables rather than hardcoding if it uses CSS vars.

- [ ] **Step 7: Verify (type-check)**

Run:
```bash
cd apps/desktop && pnpm exec tsc --noEmit
```
Expected: no new errors referencing `MapView.tsx`. (Unused-prop warnings are fine until Task 6 wires them.)

- [ ] **Step 8: Commit**

```bash
git add apps/desktop/src/renderer/components/MapView.tsx apps/desktop/src/renderer/components/MapView.css
git commit -m "feat(map): add right-click context menu with three actions"
```

---

## Task 4: Frontend — Street View dialog

**Files:**
- Modify: `apps/desktop/package.json` (add `pannellum`)
- Create: `apps/desktop/src/renderer/components/StreetViewDialog.tsx`
- Create: `apps/desktop/src/renderer/components/StreetViewDialog.css`

- [ ] **Step 1: Add pannellum**

Run:
```bash
cd apps/desktop && pnpm add pannellum
```
Expected: `pannellum` added to `dependencies`. (pannellum ships its own CSS at `pannellum/build/pannellum.css` and JS at `pannellum/build/pannellum.js`.)

- [ ] **Step 2: Confirm pannellum's global API**

pannellum exposes a global `pannellum.viewer(container, config)`. We import the JS for its side effect and the CSS for styling. Verify the files exist:
```bash
ls apps/desktop/node_modules/pannellum/build/pannellum.js apps/desktop/node_modules/pannellum/build/pannellum.css
```
Expected: both paths listed.

- [ ] **Step 3: Create the dialog component**

Create `apps/desktop/src/renderer/components/StreetViewDialog.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import 'pannellum/build/pannellum.css'
import 'pannellum/build/pannellum.js'
import './StreetViewDialog.css'

// pannellum attaches itself to window.
declare global {
  interface Window {
    pannellum?: {
      viewer: (el: HTMLElement, config: Record<string, unknown>) => { destroy: () => void }
    }
  }
}

interface StreetViewMeta {
  found: boolean
  pano_id?: string
  date?: string | null
  address?: string | null
  error?: string
}

interface StreetViewDialogProps {
  target: { lng: number; lat: number } | null
  onClose: () => void
}

const API = 'http://localhost:8765/api/streetview'

export default function StreetViewDialog({ target, onClose }: StreetViewDialogProps) {
  const [meta, setMeta] = useState<StreetViewMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const viewerHostRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<{ destroy: () => void } | null>(null)

  // Escape to close.
  useEffect(() => {
    if (!target) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [target, onClose])

  // Fetch metadata when target changes.
  useEffect(() => {
    if (!target) { setMeta(null); setError(null); return }
    let cancelled = false
    setLoading(true)
    setError(null)
    setMeta(null)
    fetch(`${API}/meta?lat=${target.lat}&lng=${target.lng}`)
      .then((r) => r.json())
      .then((d: StreetViewMeta) => { if (!cancelled) setMeta(d) })
      .catch((e) => { if (!cancelled) setError(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [target])

  // Init pannellum when we have a pano id.
  useEffect(() => {
    if (!meta?.found || !meta.pano_id || !viewerHostRef.current) return
    if (!window.pannellum) { setError('360° viewer failed to load.'); return }
    const host = viewerHostRef.current
    const viewer = window.pannellum.viewer(host, {
      type: 'equirectangular',
      panorama: `${API}/pano?pano_id=${encodeURIComponent(meta.pano_id)}&zoom=3`,
      autoLoad: true,
      showControls: true,
      crossOrigin: 'anonymous',
    })
    viewerRef.current = viewer
    return () => {
      try { viewer.destroy() } catch { /* ignore */ }
      viewerRef.current = null
    }
  }, [meta])

  if (!target) return null

  return (
    <div className="sv-overlay" onClick={onClose}>
      <div className="sv-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="sv-header">
          <div className="sv-title">
            📍 {meta?.address || `${target.lat.toFixed(5)}, ${target.lng.toFixed(5)}`}
            {meta?.date ? <span className="sv-date"> · {meta.date}</span> : null}
          </div>
          <button className="sv-close" onClick={onClose}>✕</button>
        </div>
        <div className="sv-body">
          {loading && <div className="sv-status">Loading Street View…</div>}
          {!loading && error && <div className="sv-status">⚠ {error}</div>}
          {!loading && meta && !meta.found && (
            <div className="sv-status">No Street View imagery here.</div>
          )}
          {!loading && meta?.found && (
            <div ref={viewerHostRef} className="sv-viewer" />
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Create the dialog styles**

Create `apps/desktop/src/renderer/components/StreetViewDialog.css`:

```css
.sv-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
}
.sv-dialog {
  width: min(90vw, 1100px);
  height: min(85vh, 720px);
  background: #1a1a1a;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #2a2a2a;
  color: #e0e0e0;
  font-size: 14px;
}
.sv-date { color: #9a9a9a; }
.sv-close {
  background: transparent;
  border: none;
  color: #c0c0c0;
  font-size: 16px;
  cursor: pointer;
}
.sv-close:hover { color: #fff; }
.sv-body { flex: 1; position: relative; }
.sv-viewer { width: 100%; height: 100%; }
.sv-status {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #b0b0b0;
  font-size: 14px;
}
```

- [ ] **Step 5: Verify (type-check)**

Run:
```bash
cd apps/desktop && pnpm exec tsc --noEmit
```
Expected: no errors in `StreetViewDialog.tsx`. If TS complains about the `pannellum.js` import having no types, the `declare global` block covers the runtime global; the side-effect import may need `// @ts-expect-error` above the `import 'pannellum/build/pannellum.js'` line if a "could not find declaration file" error appears — add it only if the error occurs.

- [ ] **Step 6: Commit**

```bash
git add apps/desktop/package.json apps/desktop/pnpm-lock.yaml apps/desktop/src/renderer/components/StreetViewDialog.tsx apps/desktop/src/renderer/components/StreetViewDialog.css
git commit -m "feat(streetview): add 360° Street View dialog with pannellum"
```

---

## Task 5: Frontend — ChatPanel message injection

**Files:**
- Modify: `apps/desktop/src/renderer/components/ChatPanel.tsx`

- [ ] **Step 1: Add the prop to `ChatPanelProps`**

In `ChatPanel.tsx`, add to the `ChatPanelProps` interface (after `documentImage`):

```typescript
  injectedMessage?: { text: string; nonce: number } | null
```

Add it to the destructured params:

```typescript
  documentImage,
  injectedMessage,
```

- [ ] **Step 2: Add a one-shot send effect**

After the existing `pendingInputRef` effect (the one keyed on `activeConversation?.id`), add a `useRef` to track the last-handled nonce and an effect:

```typescript
  const lastInjectedNonceRef = useRef<number>(0)

  useEffect(() => {
    if (!injectedMessage) return
    if (injectedMessage.nonce === lastInjectedNonceRef.current) return
    lastInjectedNonceRef.current = injectedMessage.nonce
    if (isStreaming) return
    if (!activeConversation) {
      // No conversation yet — stash it; the activeConversation effect will send.
      pendingInputRef.current = injectedMessage.text
      onCreateConversation()
      return
    }
    sendMessageDirect(injectedMessage.text)
  }, [injectedMessage]) // eslint-disable-line react-hooks/exhaustive-deps
```

> This reuses the existing `pendingInputRef` + `activeConversation?.id` effect already in the file (it calls `sendMessageDirect(pending)` once a conversation exists), so the "no active conversation" case is handled without duplicating send logic.

- [ ] **Step 3: Verify (type-check)**

Run:
```bash
cd apps/desktop && pnpm exec tsc --noEmit
```
Expected: no errors in `ChatPanel.tsx`.

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src/renderer/components/ChatPanel.tsx
git commit -m "feat(chat): add injectedMessage prop for one-shot external prompts"
```

---

## Task 6: Frontend — wire everything in App.tsx

**Files:**
- Modify: `apps/desktop/src/renderer/App.tsx`

- [ ] **Step 1: Import the dialog**

Near the other component imports (after `import ChatPanel ...`):

```typescript
import StreetViewDialog from './components/StreetViewDialog'
```

- [ ] **Step 2: Add state for the dialog and injected message**

Near the other `useState`s (after `mapActions`):

```typescript
  const [streetViewTarget, setStreetViewTarget] = useState<{ lng: number; lat: number } | null>(null)
  const [injectedMessage, setInjectedMessage] = useState<{ text: string; nonce: number } | null>(null)
```

- [ ] **Step 3: Add the three handlers**

After `handleMapAction` (around line 788), add:

```typescript
  const handleRightClickAddMarker = useCallback(
    (lng: number, lat: number) => {
      // Place immediately with a coordinate label, then upgrade to the
      // reverse-geocoded address when it resolves. Never block the pin.
      appendMarkersToLayer([{ lng, lat, label: `${lat.toFixed(5)}, ${lng.toFixed(5)}` }])
      fetch(`http://localhost:8765/api/geocode/reverse?lat=${lat}&lng=${lng}`)
        .then((r) => r.json())
        .then((d: { display_name?: string | null }) => {
          if (!d?.display_name) return
          setLayers((prev) =>
            prev.map((l) => {
              if (l.name.toLowerCase() !== AI_MARKERS_LAYER.toLowerCase()) return l
              const features = [...(l.data?.features || [])]
              // Update the most-recently-added point matching these coords.
              for (let i = features.length - 1; i >= 0; i--) {
                const g = features[i].geometry
                if (g?.type === 'Point' && g.coordinates[0] === lng && g.coordinates[1] === lat) {
                  features[i] = {
                    ...features[i],
                    properties: { ...features[i].properties, label: d.display_name },
                  }
                  break
                }
              }
              return { ...l, data: { type: 'FeatureCollection', features } as FeatureCollection }
            }),
          )
        })
        .catch(() => { /* keep coordinate label */ })
    },
    [appendMarkersToLayer],
  )

  const handleRightClickStreetView = useCallback((lng: number, lat: number) => {
    setStreetViewTarget({ lng, lat })
  }, [])

  const handleRightClickAskChat = useCallback(
    (lng: number, lat: number) => {
      setActiveRightTab('chat')
      const text =
        `Tell me everything you can about this location (${lat.toFixed(5)}, ${lng.toFixed(5)}): ` +
        `the address/neighborhood, nearby amenities, demographics, weather, and any notable features. Use your tools.`
      setInjectedMessage((prev) => ({ text, nonce: (prev?.nonce || 0) + 1 }))
    },
    [],
  )
```

> Confirm the exact names while editing: the markers layer constant is `AI_MARKERS_LAYER` (defined ~line 72), the upsert/append helper is `appendMarkersToLayer` (~line 534), the right-tab setter is `setActiveRightTab`, and layers setter is `setLayers`. Adjust if any differ.

- [ ] **Step 4: Pass the props to `MapView`**

In the `<MapView ... />` JSX (around line 1195), add after `onLayerStyleChange={handleLayerStyleChange}`:

```tsx
                  onAddMarker={handleRightClickAddMarker}
                  onOpenStreetView={handleRightClickStreetView}
                  onAskChat={handleRightClickAskChat}
```

- [ ] **Step 5: Pass `injectedMessage` to `ChatPanel`**

In the `<ChatPanel ... />` JSX (around line 1239), add after `documentImage={...}`:

```tsx
                injectedMessage={injectedMessage}
```

- [ ] **Step 6: Render the dialog**

Just before the final closing `</div>` of the App return (after the `.app-body` div / outermost wrapper close, around line 1267), add:

```tsx
      <StreetViewDialog target={streetViewTarget} onClose={() => setStreetViewTarget(null)} />
```

> Place it inside the top-level App wrapper div so it overlays everything. The `.sv-overlay` uses `position: fixed`, so exact DOM position within the wrapper doesn't matter.

- [ ] **Step 7: Verify (type-check)**

Run:
```bash
cd apps/desktop && pnpm exec tsc --noEmit
```
Expected: no errors. All three MapView props and ChatPanel's `injectedMessage` are now supplied.

- [ ] **Step 8: Commit**

```bash
git add apps/desktop/src/renderer/App.tsx
git commit -m "feat(app): wire right-click marker, Street View dialog, and ask-chat"
```

---

## Task 7: End-to-end manual verification

**Files:** none (verification only)

- [ ] **Step 1: Start the app**

Ensure backend is running (`pnpm dev:backend` or the uvicorn command), then:
```bash
pnpm dev
```
The Electron window opens with the map.

- [ ] **Step 2: Verify the context menu**

Right-click anywhere on the map. Expected: menu appears at the cursor with three items. Press `Escape` → closes. Right-click again, then left-click elsewhere → closes. Right-click then pan the map → closes.

- [ ] **Step 3: Verify Add marker**

Right-click over a known street (e.g. a city center) → **Add marker here**. Expected: a pin appears immediately labeled with coordinates, then within ~1–2s the label updates to a street address. Switch to the Layers tab → "AI Markers" layer present. Reload the app (Cmd+R) with a workspace open → marker persists.

- [ ] **Step 4: Verify Street View**

Right-click over a major road → **Street View**. Expected: dialog opens, shows "Loading…", then a navigable 360° panorama you can drag around; header shows address + date. Close with ✕ / Escape / backdrop click.

Right-click over open ocean → **Street View**. Expected: "No Street View imagery here." empty state, no crash.

- [ ] **Step 5: Verify Ask chat**

With no conversation active, right-click → **Ask chat about this place**. Expected: right panel switches to Chat, a new conversation is created, the templated prompt auto-sends, and the AI responds (calling tools like geocode/demographics/weather). Try again with an existing conversation active → prompt sends into it.

- [ ] **Step 6: Final commit (if any verification fixes were needed)**

```bash
git add -A
git commit -m "fix(right-click): verification fixes"
```
(Skip if no fixes were necessary.)

---

## Self-Review Notes

- **Spec coverage:** add-marker (Task 6 §3 + Task 2), Street View dialog/360°/empty-state (Tasks 1, 4, 6), ask-chat auto-send + create-conversation (Tasks 5, 6), reverse-geocode label (Tasks 2, 6), context menu + close behaviors (Task 3), dependencies `streetlevel`/`pannellum` (Tasks 1, 4), error handling (Task 1 502s, Task 4 states, Task 6 catch), persistence via AI Markers layer (Task 6). All covered.
- **Type consistency:** `appendMarkersToLayer({lng,lat,label})`, `AI_MARKERS_LAYER`, `setActiveRightTab`, `injectedMessage:{text,nonce}`, `streetViewTarget:{lng,lat}`, `setMeta`/`StreetViewMeta` — names consistent across tasks.
- **PyInstaller (prod):** out of scope for `pnpm dev` verification, but before `pnpm package`, confirm `streetlevel` is collected into the frozen binary (add `--collect-all streetlevel` / hidden import to the PyInstaller spec if the frozen backend fails to import it). Flagged in the design spec.
