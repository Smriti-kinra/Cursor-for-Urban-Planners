# Typed Artifacts — Design Spec

**Date:** 2026-05-29
**Status:** Approved for planning

## Problem

Today an "artifact" is a single plain-text database row: `artifacts(id, title, content TEXT, artifact_type, created_at, updated_at)`. `artifact_type` is only a badge label (`note|analysis|report|sketch`), and the frontend renders every artifact as `<p>{content}</p>` — plain text, no markdown, no images, no tables, no geometry.

The product vision treats "artifact" as a typed container for any saved output: rich text, attribute tables (e.g. from shapefiles), exported map images (PNG/PDF), and saved geometry. The current single-TEXT-column model cannot represent these. This redesign evolves artifacts into a typed system supporting four formats, created and consumed by both the AI and the user.

## Goals

Both the **AI** and the **user** can **create, save, view, edit, export, and re-use** artifacts across four formats:

- `markdown` — notes, analyses, reports (rich-rendered)
- `table` — structured rows/columns (e.g. shapefile attribute tables); viewable as a grid, exportable to CSV
- `image` — binary PNG/PDF (e.g. map-region export); stored as a file, shown as a thumbnail
- `geojson` — saved map features; re-addable to the map as a layer

Re-use capabilities: re-add geometry to the map, reference artifacts in chat, export/download in native format, edit in place.

## Non-Goals (explicitly out of scope)

- **AI emitting binary images.** The AI creates `markdown`/`table`/`geojson` only. Images originate from the map-export UI path. The `create_artifact` tool rejects `format: image` with a clear message.
- **Editing image content.** Image artifacts support rename/retitle only, not pixel editing.
- **Report-generation engine.** Deferred by user decision.
- **New map action for re-add.** Re-adding geometry reuses the existing `add_geojson` action; no new action tool is introduced.
- **Shapefile support beyond Phase 5.** The app currently loads only `.geojson`; the backend has no shapefile library. Shapefile reading + table extraction is isolated to the final phase.

## Data Model

Migration adds index 1→2 in `database.py:_MIGRATIONS`. Existing rows are preserved.

```sql
ALTER TABLE artifacts ADD COLUMN format TEXT NOT NULL DEFAULT 'markdown';
ALTER TABLE artifacts ADD COLUMN file_path TEXT;   -- relative path under artifacts_store/, NULL for inline
ALTER TABLE artifacts ADD COLUMN meta TEXT;        -- JSON string, NULL ok
```

Final columns: `id, title, content, artifact_type, format, file_path, meta, created_at, updated_at`.

**Two orthogonal fields** (key design decision):

- `artifact_type` — *semantic* label, unchanged: `note | analysis | report | sketch`. Drives the badge.
- `format` — *payload kind*, NEW: `markdown | table | image | geojson`. Drives storage + rendering.

They do not collide: e.g. "an `analysis` (type) that is a `table` (format)" is expressible.

### Payload storage by format

| format | `content` column | `file_path` | `meta` JSON |
|---|---|---|---|
| `markdown` | the markdown text | — | — |
| `table` | JSON `{columns:[...], rows:[[...]]}` | — | `{row_count}` |
| `geojson` | the GeoJSON string | — | `{bbox, feature_count}` |
| `image` | — | `artifacts_store/<id>.png\|pdf` | `{width, height, mime}` |

**Existing rows** migrate to `format='markdown'`, `file_path=NULL`. Their plain-text content renders correctly as markdown.

**File store:** `<backend>/artifacts_store/`, anchored exactly like `DB_PATH` in `database.py` so CWD does not matter. Filenames keyed by artifact id.

## Backend API

### New module: `tools/artifact_store.py`

Single home for file-handling + validation, called by both the HTTP router and the AI tools so logic is not duplicated.

```
save_artifact(title, artifact_type, format, *, content=None, file_bytes=None, meta=None) -> dict
read_artifact(id) -> dict          # includes resolved payload
delete_artifact(id) -> None        # also removes file_path from disk
ARTIFACTS_DIR                      # <backend>/artifacts_store/, created on import like DB_PATH
```

- Validates `format` against the four allowed values.
- `image`: writes bytes to `artifacts_store/<id>.<ext>`, stores relative `file_path`, computes `meta` (width/height/mime via **Pillow** — new dependency).
- `table`/`geojson`: validates JSON shape, stores inline in `content`, derives `meta` (row_count / bbox+feature_count).
- `markdown`: stores text as-is.

### HTTP router (`routers/artifacts.py`) — extend, not rewrite

- `POST /api/artifacts` — accept `format`, `meta`, and multipart binary upload for images. Text/table/geojson stay JSON-body.
- `GET /api/artifacts` — list returns `format` + `meta` + a content preview (not full binary).
- `GET /api/artifacts/{id}` — full payload; images stream the file.
- `GET /api/artifacts/{id}/download` — **NEW**: serve native file (`.md`/`.csv`/`.png`/`.pdf`/`.geojson`) with download headers. Powers UI export.
- `PUT /api/artifacts/{id}` — edit-in-place: title/content/meta. (Image content not editable — rename/retitle only.)
- `DELETE /api/artifacts/{id}` — also unlink the file.

`models.py`: extend `ArtifactCreate`/`ArtifactUpdate` with `format`, `file_path`, `meta`.

### AI tools (`tools/utility.py`)

- `create_artifact` gains a `format` param (default `markdown`, back-compatible). `table` → `{columns, rows}`; `geojson` → Feature/FeatureCollection. `image` rejected with a clear message.
- `list_artifacts` / `get_artifact` extended to surface `format` + `meta` so the AI knows what it is pulling into context.
- **Re-add geometry to map** needs no new tool: `get_artifact` on a `geojson` artifact returns geometry; the existing `add_geojson` action puts it on the map. Documented in the system prompt.

### New dependency

- **Pillow** — computes image width/height/mime on save. Added to `packages/backend/requirements.txt`. Must work in the PyInstaller-frozen prod build.

## Frontend Rendering (`ArtifactsPanel.tsx`)

The panel becomes a **format-aware renderer** — a switch on `format`:

| format | rendering | re-use controls |
|---|---|---|
| `markdown` | `react-markdown` + `remark-gfm` (already used in `ChatPanel.tsx`; no new dep) | Edit, Download (.md) |
| `table` | HTML `<table>` grid from `{columns, rows}`, scrollable | Edit (cell/title), Download (.csv) |
| `image` | `<img src={/api/artifacts/{id}/download}>` thumbnail → click to enlarge | Download (.png/.pdf) |
| `geojson` | summary (feature count, bbox) + "Add to map" button | Add to map, Download (.geojson) |

**Interactions:**

- **"Add to map"** (geojson) — dispatches the existing `add_geojson` map action via the `setMapActions` queue already threaded through `App.tsx`. This is the user-side re-add path.
- **Edit-in-place** — title always editable; markdown/table content editable inline, saved via `PUT`. Images: title only.
- **Download** — hits `GET /api/artifacts/{id}/download`.
- **Create form** gains a **format selector**; fields adapt (textarea for markdown, table builder / JSON paste for table, file picker for image, geojson paste / "save current layer" for geometry).

`types.ts`: extend the `Artifact` interface with `format`, `file_path`, `meta`.

## Map → Image Artifact

The export *rendering* already exists in `App.tsx`: `handleExportMapPng` (`canvas.toBlob()` PNG) and `handleExportPdf` (`jspdf` A4 render). `MapView.getCanvas()` exposes a canvas with `preserveDrawingBuffer: true`. `jspdf` is already a dependency. Today these only trigger a browser download.

**Gap:** route the produced output to an artifact.

**Added:**

1. **"Save as artifact" path.** Refactor the two handlers so the produced PNG blob / PDF `ArrayBuffer` can be POSTed to `POST /api/artifacts` (multipart, `format:image`) in addition to the existing download. Download buttons stay.
2. **AI-suggested name (opt-in).** Export is instant with an auto title (top visible layer name, else `Map export — <date>`). A **"Suggest name with AI"** button regenerates the title on demand by calling the chat model with map context (bounds + visible layer names). No blocking LLM call in the default export path.
3. **Format choice.** Export menu: PNG (default) or PDF.

**Flow:**

```
User clicks Export ▾  → PNG | PDF | Save to artifacts
   Save to artifacts → render blob (existing code)
                     → POST /api/artifacts (multipart, format=image, title=auto)
                     → artifact_store writes file + Pillow meta
                     → ArtifactsPanel shows thumbnail
   "Suggest name with AI" (optional) → model titles using map context → PUT title
```

## Implementation Phases

Each phase is independently shippable and testable.

1. **Schema + store + API** — migration 1→2; `tools/artifact_store.py`; extend `routers/artifacts.py` (+ `/download`); extend `models.py`; add Pillow to `requirements.txt`. Verify migration preserves existing rows.
2. **Format-aware panel** — `ArtifactsPanel.tsx` renders all four formats; edit-in-place; download; "Add to map" for geojson; extend `Artifact` type. Reuse `react-markdown`.
3. **AI create** — extend `create_artifact` with `format` (markdown/table/geojson; reject image); surface `format`+`meta` in `list_artifacts`/`get_artifact`; document geojson→`add_geojson` re-add path in the system prompt.
4. **Map → image artifact** — refactor existing export handlers to optionally POST a `format:image` artifact; export format menu; opt-in "Suggest name with AI".
5. **Shapefile table extraction** (deferred, last) — add shapefile reading (`pyshp` or `geopandas`), extract attribute table → `table` artifact. Isolated so the new dependency + PyInstaller risk cannot block phases 1–4.

## Testing

The repo has no test suite; the quality bar is "golden paths work, no regressions" (CLAUDE.md).

- Manual golden-path verification per phase, run in the Electron window via the `run` skill.
- Phase 1: a focused Python check that the migration upgrades an existing DB without data loss and round-trips each format through `artifact_store`.
- Regression watch: the chat → tool-call → map-action flow must keep working.

## Key Files

- `packages/backend/database.py` — migrations, DB path anchoring.
- `packages/backend/routers/artifacts.py` — HTTP CRUD.
- `packages/backend/models.py` — `ArtifactCreate`/`ArtifactUpdate`.
- `packages/backend/tools/utility.py` — `create_artifact`/`list_artifacts`/`get_artifact`.
- `packages/backend/tools/artifact_store.py` — NEW shared store module.
- `apps/desktop/src/renderer/components/ArtifactsPanel.tsx` — format-aware rendering.
- `apps/desktop/src/renderer/App.tsx` — export handlers, `setMapActions` queue.
- `apps/desktop/src/renderer/types.ts` — `Artifact` interface.
