---
name: add-map-action
description: Use when adding a new map operation the AI agent can drive (fly, fit, draw, mark, layer style). Encodes the procedure across the backend action contract, the MapView frontend handler, and the discriminated union in types.ts — three files must be touched in lockstep or the action silently fails.
---

# Add Map Action

A "map action" is an LLM-callable function whose execution happens in the **frontend**, not the backend. The backend recognizes the tool name, forwards the args to the renderer over the WebSocket as `{type: "action", action, payload}`, and `MapView.tsx` translates that into a MapLibre operation (fly, fitBounds, addSource/addLayer, etc.).

This skill is for adding a **new action**. If you are instead adding a backend tool that returns data the model uses (OSM query, GIS computation, weather lookup), use **[[add-mcp-tool]]** instead — different procedure.

## The contract, end to end

```
LLM tool call: { name: "fly_to", arguments: { lat, lng, zoom } }
                              ↓
routers/chat.py:_execute_tool()      ← name is in _ACTION_TOOLS set
                              ↓
WebSocket frame:
  { "type": "action", "action": "fly_to", "payload": { lat, lng, zoom } }
                              ↓
ChatPanel.tsx onmessage              ← parses, calls onMapAction({type, payload})
                              ↓
App.tsx setMapActions(prev => [...prev, action])   ← queue
                              ↓
MapView.tsx useEffect on mapActions  ← switch on type, runs MapLibre ops
                              ↓
onActionsProcessed() → setMapActions([])           ← drain
```

## The three files (all required)

| # | File | What you add |
|---|---|---|
| 1 | `packages/backend/routers/chat.py` | Tool name in `_ACTION_TOOLS` + tool def in `action_defs` + mention in `SYSTEM_PROMPT` |
| 2 | `apps/desktop/src/renderer/types.ts` | New variant in the `MapAction` discriminated union |
| 3 | `apps/desktop/src/renderer/components/MapView.tsx` | `case 'your_action':` branch in the switch inside the `mapActions` useEffect |

**Skip any of these and the action silently fails or won't compile:**
- Skip the `_ACTION_TOOLS` entry → backend executes it as a regular tool, no map effect.
- Skip the tool def → model can't see the tool, never calls it.
- Skip the `MapAction` union variant → TS won't compile until the switch in MapView is exhaustive.
- Skip the MapView case → backend says "success" but the map doesn't move. Most common bug.
- Skip the system prompt mention → tool exists but model rarely picks it; the system prompt is the bias.

## Procedure

### 1. Pick the action name and shape

Names use snake_case verbs: `fly_to`, `fit_bounds`, `draw_circle`, `set_layer_style`. Read the existing list in `routers/chat.py` `_ACTION_TOOLS` before naming — match the prevailing style.

Sketch the payload as a JSON Schema. Examples to model after, in `routers/chat.py` `action_defs`:
- Single point: `fly_to` (lat, lng, zoom)
- Bounding box: `fit_bounds` (south, west, north, east)
- Geometry blob: `add_geojson` (geojson, name, color)
- Layer mutation: `set_layer_style` (layer_name, fill_color, line_color, opacity)

Default rule: `required` lists only the truly required keys; everything stylistic (colors, widths, opacity) goes optional with a sensible frontend default.

### 2. Backend (`routers/chat.py`)

**a.** Add the name to `_ACTION_TOOLS`. Just a string literal in the `set`.

**b.** Append a tuple to `action_defs` inside `_build_tools()`. Pattern:
```python
("your_action", "One-line description for the model", {
    "type": "object",
    "properties": {
        "param_a": {"type": "number"},
        "param_b": {"type": "string"},
    },
    "required": ["param_a"],
}),
```

The dispatch at `_execute_tool()` auto-handles anything in `_ACTION_TOOLS` — it forwards args to `_send_action(ws, name, args)` without a per-action branch. **Do not add a branch to `_execute_tool()`** unless your action also needs server-side side effects (rare; `create_artifact` does this and is the only example).

### 3. Frontend types (`types.ts`)

`MapAction` is a discriminated union. Add a variant matching the backend schema exactly:

```ts
| { type: 'your_action'; payload: { param_a: number; param_b?: string } }
```

Optional schema params become optional TS props. Once you save the file, `MapView.tsx`'s switch will fail to type-check until you add the case in step 4 — that's the safety net.

### 4. Frontend handler (`MapView.tsx`)

Open the `mapActions` useEffect. Inside the `for (const action of mapActions)` loop is a `switch (type)`. Add a `case 'your_action':` branch. Reference patterns by category:

| Action shape | Reference | Notes |
|---|---|---|
| Camera move | `case 'fly_to'` | `map.flyTo({...})` |
| Camera bounds | `case 'fit_bounds'` | `map.fitBounds([...])` |
| Marker | `case 'add_marker'` | DOM element + `maplibregl.Marker`, push to `aiMarkersRef` |
| New geometry layer | `case 'draw_polygon'` or `case 'add_geojson'` | `map.addSource()` + `map.addLayer()`, track id in `aiShapeIdsRef` for cleanup |
| Mutate existing layer | `case 'highlight_features'` or `set_layer_style` | look up by `layer_name`, use `map.setPaintProperty()` |

**Cleanup tracking.** If your action adds sources/layers, add their ids to one of:
- `aiMarkersRef.current.push(marker)` — for markers (cleared by `clear_markers`)
- `aiShapeIdsRef.current.add(layerId)` — for shape layers

Without this, the canvas accumulates orphan layers across the session.

### 5. System prompt (`routers/chat.py`)

Find the `AVAILABLE TOOLS:` block in `SYSTEM_PROMPT`. Add your action name to the matching category line, e.g. under `Navigate:`, `Markers:`, `Layers:`. If the action has a calling rule (e.g. "always pass color"), add a numbered rule under `IMPORTANT RULES:` lower in the prompt.

### 6. Verify

```bash
pnpm dev
```

In the Electron window's chat panel, ask the model to do something that should trigger your action ("zoom to Paris", "draw a 5km circle around the city center"). Confirm:
- The chat shows `Using your_action...` (`tool_use` status from the WebSocket).
- The map actually does the thing.
- No console errors in the renderer DevTools.

If the chat says success but the map didn't move, you skipped step 4 (frontend handler). If the model never calls the action, you skipped step 5 (system prompt) or the tool def schema is malformed.

## When NOT to add a map action

- **The action is "show this data on the map" given a tool result.** Use the auto-display branch in `_execute_tool()` instead — see [[add-mcp-tool]] step 3. The map already handles `add_geojson`; you don't need a per-result-type action.
- **The thing is a frontend-only UX feature** (e.g., "toggle the layer panel"). That's not an LLM action; wire it into a button or keyboard shortcut.
- **The thing is a backend computation that returns data**, not a map effect. That's an MCP server tool — see [[add-mcp-tool]].

## Files referenced

- `packages/backend/routers/chat.py` — `_ACTION_TOOLS`, `SYSTEM_PROMPT`, `action_defs` inside `_build_tools()`, `_execute_tool()` action dispatch.
- `apps/desktop/src/renderer/components/MapView.tsx` — `mapActions` useEffect, switch statement.
- `apps/desktop/src/renderer/components/ChatPanel.tsx` — WebSocket dispatch.
- `apps/desktop/src/renderer/App.tsx` — `handleMapAction`, `mapActions` state.
- `apps/desktop/src/renderer/types.ts` — `MapAction` discriminated union.

Line numbers drift; grep by section comments (`# ── Action tool names`, `# ── Map actions`, `case 'fly_to':`) to locate sections reliably.
