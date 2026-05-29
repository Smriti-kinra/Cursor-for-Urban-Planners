# Deep Research Report Generation

**Date:** 2026-05-29  
**Model:** `o4-mini-deep-research`  
**Status:** Approved

---

## Overview

Replace the existing synchronous `/api/reports/generate` endpoint with a streaming SSE endpoint that uses OpenAI's Responses API with `o4-mini-deep-research` + `web_search`. The user triggers report generation from ArtifactsPanel, sees live progress as the model browses the web, and downloads the final report as `.md` or `.pdf`.

---

## Architecture

```
ArtifactsPanel (React)
  │  POST /api/reports/stream  (body: ReportRequest, response: text/event-stream)
  │
  ▼
reports.py  (FastAPI SSE endpoint)
  │  client.responses.create(stream=True, model="o4-mini-deep-research",
  │    tools=[{"type":"web_search"}], max_tool_calls=20)
  │
  ▼
OpenAI Responses API  →  web search calls  →  final message
```

No new files. `reports.py` gains one new route; `ArtifactsPanel.tsx` gains a report generation UI section.

---

## Backend

### New endpoint: `POST /api/reports/stream`

- **Content-Type response:** `text/event-stream`
- **Request body:** same `ReportRequest` as today (`chat_history`, `map_context`, `artifacts`)
- **Client:** uses `AsyncOpenAI` Responses API (`client.responses.create`) with `stream=True`
- **Model:** `o4-mini-deep-research`
- **Tools:** `[{"type": "web_search"}]`
- **`max_tool_calls`:** 20

### SSE event types emitted

| Event | Data shape | Purpose |
|---|---|---|
| `tool_call` | `{"action": "search", "query": "..."}` or `{"action": "open_page", "url": "..."}` | Live progress step |
| `message` | `{"markdown": "...full report text..."}` | Final report, triggers download UI |
| `error` | `{"detail": "..."}` | Backend/API error |

### Prompt construction

The backend builds a detailed prompt from the request:
1. **Location context** — center lat/lng, zoom, bounds, basemap
2. **Layers** — for each layer: name, feature count, geometry types, properties, and full coordinates if ≤5 features / ≤200 coords, else bbox
3. **Markers & drawings** — already present in the layers array ("AI Markers" layer + any draw layers)
4. **Bookmarks** — named areas the user has saved
5. **Conversation** — full chat history formatted as User/Assistant turns
6. **Artifacts** — all saved artifacts with title, type, and content

The system prompt instructs the model to generate a structured professional urban planning report with sections: Executive Summary, Site Analysis, Key Findings, Recommendations, Appendix (data sources, methodology).

### Keep existing `/generate` endpoint

The old synchronous endpoint remains untouched for now (no callers in the frontend currently, but keep for compatibility).

---

## Frontend

### ArtifactsPanel changes

**Idle state** (no report in progress, no report ready):
- "Generate Report" button at the top of the panel

**In-progress state** (SSE stream open):
- Button replaced by progress area
- Each `tool_call` SSE event appends a line to a scrollable log:
  - Active: `[spinner] Searching: <query>` or `[spinner] Opening: <url>`
  - Completed (once next event arrives): `✓ <previous line>`
- Cancel button (closes the `EventSource`, aborts the fetch)

**Done state** (final `message` event received):
- Progress log collapses (or shows summary: "X searches completed")
- Two download buttons appear: `[ Download .md ]` and `[ Download PDF ]`
- "Generate new report" link to reset back to idle

**Error state:**
- Shows error message inline, "Try again" resets to idle

### Download behaviour

- **`.md`:** `Blob` with `text/markdown`, trigger `<a download>` with filename `urban-planning-report-<timestamp>.md`
- **PDF:** render markdown with jsPDF (already a dependency via `ExportPanel`). Use `doc.text()` with line wrapping. Filename `urban-planning-report-<timestamp>.pdf`

### Props required

`ArtifactsPanel` already receives nothing about chat or map from `App.tsx`. Two new props needed:
- `chatHistory: ChatMessage[]` — active conversation messages
- `mapContext: MapContext` — current map state (already computed in `App.tsx`)

The artifacts list is fetched internally by `ArtifactsPanel` via HTTP, so no new prop needed for that.

---

## Data flow (end-to-end)

1. User clicks "Generate Report" in `ArtifactsPanel`
2. Frontend opens SSE connection: `fetch('/api/reports/stream', { method: 'POST', body: JSON.stringify({ chat_history, map_context, artifacts }) })`
3. Backend streams SSE events as the model searches
4. Frontend renders each `tool_call` event as a progress line
5. On `message` event: store markdown string in state, show download buttons
6. User clicks "Download .md" → Blob download
7. User clicks "Download PDF" → jsPDF render → download

---

## Constraints & notes

- `o4-mini-deep-research` requires at least one tool — `web_search` satisfies this
- `max_tool_calls=20` caps cost/latency at roughly 1–3 minutes
- The Responses API streaming format differs from Chat Completions streaming — use `for await (chunk of stream)` on the response object and inspect `chunk.type`
- The old `chat.completions` import in `reports.py` stays for the existing `/generate` route; add `client.responses` calls for the new route
- No new DB tables or artifact records — purely a download flow
- jsPDF markdown rendering is line-by-line (no rich HTML); headings get larger font size, body gets normal size
