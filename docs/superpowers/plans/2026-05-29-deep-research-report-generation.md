# Deep Research Report Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static report generation with a streaming SSE endpoint that drives `o4-mini-deep-research` + web search, surfaced via a live progress UI in ArtifactsPanel with MD and PDF download.

**Architecture:** A new `POST /api/reports/stream` FastAPI endpoint streams SSE events (tool_call progress + final message) from the OpenAI Responses API. ArtifactsPanel gains two new props (`chatHistory`, `mapContext`), a "Generate Report" button, a live progress log, and download buttons. The old `/generate` endpoint is left untouched.

**Tech Stack:** Python `openai` Responses API (`client.responses.create(stream=True)`), FastAPI SSE via `StreamingResponse`, React `fetch` with streaming reader, `jspdf` (already installed) for PDF download.

---

## File Map

| File | Change |
|---|---|
| `packages/backend/routers/reports.py` | Add `POST /stream` SSE endpoint |
| `apps/desktop/src/renderer/components/ArtifactsPanel.tsx` | Add report generation UI + 2 new props |
| `apps/desktop/src/renderer/App.tsx` | Pass `chatHistory` and `mapContext` props to `ArtifactsPanel` |

---

### Task 1: Add `POST /api/reports/stream` SSE endpoint

**Files:**
- Modify: `packages/backend/routers/reports.py`

- [ ] **Step 1: Add the new imports and SSE helper**

Open `packages/backend/routers/reports.py`. After the existing imports add:

```python
from fastapi.responses import StreamingResponse
```

- [ ] **Step 2: Add the streaming endpoint**

After the existing `@router.post("/generate")` handler, add the following. Do not remove or modify the existing `/generate` route.

```python
STREAM_SYSTEM = (
    "You are a professional urban planning report writer. "
    "Generate a well-structured, data-driven report in clean Markdown. "
    "Use the provided conversation, map data, and artifacts as your primary source. "
    "Enrich your analysis with publicly available information about the location. "
    "Respond ONLY with the Markdown report. Always respond in English."
)

STREAM_REPORT_PROMPT = """Generate a comprehensive urban planning report based on the data below.

Structure the report with these sections:

# Urban Planning Report

## Executive Summary
(2-3 paragraph overview of the planning discussion, location, and key findings)

## Site Analysis
(Geographic context, existing conditions, basemap and layer data, drawn features, placed markers)

## Key Findings
(Main points from the conversation and analysis, enriched with current public data)

## Recommendations
(Actionable next steps based on the discussion and research)

## Appendix
(Data sources, layer descriptions, methodology notes, web sources consulted)

Be specific and professional. Reference the actual map data, drawn geometries, and conversation details provided.
---
"""


def _build_stream_prompt(request: ReportRequest) -> str:
    parts = [STREAM_REPORT_PROMPT]

    if request.map_context:
        ctx = request.map_context
        center = ctx.get("center", [])
        zoom = ctx.get("zoom", "")
        bounds = ctx.get("bounds", {})
        basemap = ctx.get("basemap", "")
        bookmarks = ctx.get("bookmarks", [])
        layers = ctx.get("layers", [])

        loc_lines = [f"**Center:** {center}", f"**Zoom:** {zoom}", f"**Basemap:** {basemap}"]
        if bounds:
            loc_lines.append(
                f"**Bounds:** W={bounds.get('west')}, S={bounds.get('south')}, "
                f"E={bounds.get('east')}, N={bounds.get('north')}"
            )
        parts.append("## Map Context\n" + "\n".join(loc_lines))

        if bookmarks:
            bm_lines = [
                f"- {b['name']}: bounds W={b['west']}, S={b['south']}, E={b['east']}, N={b['north']}"
                for b in bookmarks
            ]
            parts.append("### Bookmarks\n" + "\n".join(bm_lines))

        if layers:
            layer_lines = []
            for layer in layers:
                name = layer.get("name", "unnamed")
                count = layer.get("featureCount", 0)
                geom_types = ", ".join(layer.get("geometryTypes", []))
                props = ", ".join(layer.get("properties", []))
                visible = layer.get("visible", True)
                line = f"- **{name}** ({count} features, {geom_types}, visible={visible})"
                if props:
                    line += f"\n  Properties: {props}"
                geo = layer.get("geometry_data")
                if geo:
                    if isinstance(geo, list):
                        line += f"\n  Coordinates: {json.dumps(geo)}"
                    elif isinstance(geo, dict) and "bbox" in geo:
                        line += f"\n  Bounding box: {geo['bbox']}"
                layer_lines.append(line)
            parts.append("### Layers\n" + "\n".join(layer_lines))

    if request.chat_history:
        lines = []
        for m in request.chat_history:
            role = "User" if m.get("role") == "user" else "Assistant"
            content = m.get("content", "")
            if content:
                lines.append(f"**{role}:** {content}")
        if lines:
            parts.append("## Conversation\n" + "\n\n".join(lines))

    if request.artifacts:
        items = []
        for a in request.artifacts:
            t = a.get("artifact_type", "note")
            title = a.get("title", "")
            content = a.get("content", "")
            items.append(f"- [{t}] **{title}**: {content[:500]}")
        parts.append("## Artifacts\n" + "\n".join(items))

    return "\n\n".join(parts)


@router.post("/stream")
async def stream_report(request: ReportRequest):
    prompt = _build_stream_prompt(request)

    async def generate():
        try:
            stream = await _client.responses.create(
                model="o4-mini-deep-research",
                input=prompt,
                tools=[{"type": "web_search_preview"}],
                max_tool_calls=20,
                stream=True,
            )
            async for event in stream:
                event_type = getattr(event, "type", None)

                # Web search tool call events
                if event_type == "response.web_search_call.searching":
                    query = getattr(event, "query", "") or ""
                    data = json.dumps({"action": "search", "query": query})
                    yield f"event: tool_call\ndata: {data}\n\n"

                elif event_type == "response.web_search_call.completed":
                    pass  # already announced at searching

                # Output text delta — accumulate until done
                elif event_type == "response.output_text.done":
                    text = getattr(event, "text", "") or ""
                    if text:
                        data = json.dumps({"markdown": text})
                        yield f"event: message\ndata: {data}\n\n"

        except Exception as exc:
            data = json.dumps({"detail": str(exc)})
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 3: Verify the backend starts without errors**

```bash
cd packages/backend && source .buildenv/bin/activate && python -c "from routers.reports import router; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add packages/backend/routers/reports.py
git commit -m "feat(reports): add POST /api/reports/stream SSE endpoint with o4-mini-deep-research"
```

---

### Task 2: Pass `chatHistory` and `mapContext` props to ArtifactsPanel

**Files:**
- Modify: `apps/desktop/src/renderer/App.tsx`

- [ ] **Step 1: Update the ArtifactsPanel JSX in App.tsx**

Find the `<ArtifactsPanel` block (around line 1253) which currently reads:

```tsx
<ArtifactsPanel
  revision={artifactsRevision}
  onAddToMap={(geojson, name) => {
    setMapActions((prev) => [
      ...prev,
      { type: 'add_geojson', payload: { geojson: geojson as FeatureCollection, name } },
    ])
  }}
/>
```

Replace it with:

```tsx
<ArtifactsPanel
  revision={artifactsRevision}
  chatHistory={activeConversation?.messages ?? []}
  mapContext={mapContext}
  onAddToMap={(geojson, name) => {
    setMapActions((prev) => [
      ...prev,
      { type: 'add_geojson', payload: { geojson: geojson as FeatureCollection, name } },
    ])
  }}
/>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd apps/desktop && pnpm exec tsc --noEmit 2>&1 | head -20
```

Expected: errors only about the not-yet-updated `ArtifactsPanelProps` (will be fixed in Task 3). No other new errors.

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src/renderer/App.tsx
git commit -m "feat(artifacts): pass chatHistory and mapContext to ArtifactsPanel"
```

---

### Task 3: Add report generation UI to ArtifactsPanel

**Files:**
- Modify: `apps/desktop/src/renderer/components/ArtifactsPanel.tsx`

- [ ] **Step 1: Update the props interface**

Find:

```tsx
interface ArtifactsPanelProps {
  revision?: number
  onAddToMap: (geojson: object, name: string) => void
}
```

Replace with:

```tsx
import type { ChatMessage, MapContext } from '../types'

interface ArtifactsPanelProps {
  revision?: number
  onAddToMap: (geojson: object, name: string) => void
  chatHistory?: ChatMessage[]
  mapContext?: MapContext
}
```

Note: the `import type` line should go at the top of the file with the other imports.

- [ ] **Step 2: Add report state and logic to the component**

Find the destructuring at the top of the component function body:

```tsx
export default function ArtifactsPanel({ revision, onAddToMap }: ArtifactsPanelProps) {
```

Replace with:

```tsx
export default function ArtifactsPanel({ revision, onAddToMap, chatHistory = [], mapContext }: ArtifactsPanelProps) {
```

Then, after all the existing `useState` declarations (around line 37, after `const [editContentValue, setEditContentValue] = useState('')`), add:

```tsx
  // Report generation state
  type ReportPhase = 'idle' | 'running' | 'done' | 'error'
  const [reportPhase, setReportPhase] = useState<ReportPhase>('idle')
  const [reportSteps, setReportSteps] = useState<string[]>([])
  const [reportMarkdown, setReportMarkdown] = useState('')
  const [reportError, setReportError] = useState('')
  const reportAbortRef = useRef<AbortController | null>(null)
```

Also add `useRef` to the import at line 1 — find:

```tsx
import { useState, useEffect, useCallback } from 'react'
```

Replace with:

```tsx
import { useState, useEffect, useCallback, useRef } from 'react'
```

- [ ] **Step 3: Add the generateReport function**

After the `fetchArtifacts` function (around line 49), add:

```tsx
  const generateReport = useCallback(async () => {
    setReportPhase('running')
    setReportSteps([])
    setReportMarkdown('')
    setReportError('')

    const controller = new AbortController()
    reportAbortRef.current = controller

    // Fetch current artifacts list for context
    let artifactsContext: object[] = []
    try {
      const res = await fetch('http://localhost:8765/api/artifacts')
      if (res.ok) artifactsContext = await res.json()
    } catch { /* ignore */ }

    try {
      const res = await fetch('http://localhost:8765/api/reports/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chat_history: chatHistory.map((m) => ({ role: m.role, content: m.content })),
          map_context: mapContext ?? null,
          artifacts: artifactsContext,
        }),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) {
        setReportError('Backend returned an error. Is the server running?')
        setReportPhase('error')
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        let currentEvent = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            const raw = line.slice(6).trim()
            try {
              const payload = JSON.parse(raw)
              if (currentEvent === 'tool_call') {
                const label =
                  payload.action === 'search'
                    ? `Searching: ${payload.query}`
                    : `Opening: ${payload.url ?? payload.query ?? ''}`
                setReportSteps((prev) => [...prev, label])
              } else if (currentEvent === 'message') {
                setReportMarkdown(payload.markdown ?? '')
                setReportPhase('done')
              } else if (currentEvent === 'error') {
                setReportError(payload.detail ?? 'Unknown error')
                setReportPhase('error')
              }
            } catch { /* malformed SSE line */ }
            currentEvent = ''
          }
        }
      }

      if (reportPhase !== 'done' && reportPhase !== 'error') {
        setReportPhase('done')
      }
    } catch (err: unknown) {
      if ((err as { name?: string }).name !== 'AbortError') {
        setReportError(String(err))
        setReportPhase('error')
      }
    }
  }, [chatHistory, mapContext, reportPhase])

  const cancelReport = useCallback(() => {
    reportAbortRef.current?.abort()
    setReportPhase('idle')
    setReportSteps([])
  }, [])

  const downloadMd = useCallback(() => {
    const blob = new Blob([reportMarkdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `urban-planning-report-${Date.now()}.md`
    a.click()
    URL.revokeObjectURL(url)
  }, [reportMarkdown])

  const downloadPdf = useCallback(async () => {
    const { jsPDF } = await import('jspdf')
    const doc = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' })
    const pageWidth = doc.internal.pageSize.getWidth()
    const margin = 48
    const maxLineWidth = pageWidth - margin * 2
    let y = margin

    const addPage = () => {
      doc.addPage()
      y = margin
    }

    const checkY = (needed: number) => {
      if (y + needed > doc.internal.pageSize.getHeight() - margin) addPage()
    }

    for (const rawLine of reportMarkdown.split('\n')) {
      const line = rawLine.trimEnd()

      if (line.startsWith('# ')) {
        checkY(28)
        doc.setFontSize(20)
        doc.setFont('helvetica', 'bold')
        doc.text(line.slice(2), margin, y)
        y += 28
      } else if (line.startsWith('## ')) {
        checkY(22)
        doc.setFontSize(16)
        doc.setFont('helvetica', 'bold')
        doc.text(line.slice(3), margin, y)
        y += 22
      } else if (line.startsWith('### ')) {
        checkY(18)
        doc.setFontSize(13)
        doc.setFont('helvetica', 'bold')
        doc.text(line.slice(4), margin, y)
        y += 18
      } else if (line === '') {
        y += 8
      } else {
        doc.setFontSize(11)
        doc.setFont('helvetica', 'normal')
        const wrapped = doc.splitTextToSize(line.replace(/^\s*[-*]\s+/, '• '), maxLineWidth)
        for (const wl of wrapped) {
          checkY(14)
          doc.text(wl, margin, y)
          y += 14
        }
      }
    }

    doc.save(`urban-planning-report-${Date.now()}.pdf`)
  }, [reportMarkdown])
```

- [ ] **Step 4: Add the report UI section to the JSX**

Find the opening of the returned JSX:

```tsx
  return (
    <div className="artifacts-panel">
      <div className="artifacts-toolbar">
```

Replace with:

```tsx
  return (
    <div className="artifacts-panel">
      {/* Report generation section */}
      <div className="report-section">
        {reportPhase === 'idle' && (
          <button className="generate-report-btn" onClick={generateReport}>
            Generate Report
          </button>
        )}

        {reportPhase === 'running' && (
          <div className="report-progress">
            <div className="report-progress-header">
              <span className="report-spinner">⟳</span>
              <span>Researching…</span>
              <button className="cancel-report-btn" onClick={cancelReport}>Cancel</button>
            </div>
            <div className="report-steps">
              {reportSteps.map((step, i) => (
                <div key={i} className={`report-step ${i < reportSteps.length - 1 ? 'done' : 'active'}`}>
                  {i < reportSteps.length - 1 ? '✓' : '⟳'} {step}
                </div>
              ))}
            </div>
          </div>
        )}

        {reportPhase === 'done' && (
          <div className="report-done">
            <span className="report-done-label">✓ Report ready</span>
            <div className="report-download-btns">
              <button className="download-md-btn" onClick={downloadMd}>Download .md</button>
              <button className="download-pdf-btn" onClick={downloadPdf}>Download PDF</button>
            </div>
            <button className="report-reset-btn" onClick={() => { setReportPhase('idle'); setReportMarkdown(''); setReportSteps([]); }}>
              Generate new report
            </button>
          </div>
        )}

        {reportPhase === 'error' && (
          <div className="report-error">
            <span>Error: {reportError}</span>
            <button className="report-reset-btn" onClick={() => setReportPhase('idle')}>Try again</button>
          </div>
        )}
      </div>

      <div className="artifacts-toolbar">
```

- [ ] **Step 5: Add CSS for the report section**

Open `apps/desktop/src/renderer/components/ArtifactsPanel.css` and append at the end:

```css
/* Report generation */
.report-section {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border, #333);
}

.generate-report-btn {
  width: 100%;
  padding: 7px 0;
  background: var(--accent, #3b82f6);
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.generate-report-btn:hover {
  opacity: 0.85;
}

.report-progress {
  font-size: 12px;
}

.report-progress-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-weight: 600;
}

.report-spinner {
  display: inline-block;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.cancel-report-btn {
  margin-left: auto;
  background: none;
  border: 1px solid #666;
  color: #aaa;
  border-radius: 3px;
  cursor: pointer;
  font-size: 11px;
  padding: 2px 6px;
}

.report-steps {
  max-height: 140px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.report-step {
  font-size: 11px;
  color: #aaa;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.report-step.active {
  color: #e2e8f0;
}

.report-step.done {
  color: #4ade80;
}

.report-done {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.report-done-label {
  font-size: 12px;
  color: #4ade80;
  font-weight: 600;
}

.report-download-btns {
  display: flex;
  gap: 6px;
}

.download-md-btn,
.download-pdf-btn {
  flex: 1;
  padding: 6px 0;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.download-md-btn {
  background: #374151;
  color: #e2e8f0;
}

.download-pdf-btn {
  background: #1d4ed8;
  color: #fff;
}

.download-md-btn:hover { opacity: 0.85; }
.download-pdf-btn:hover { opacity: 0.85; }

.report-reset-btn {
  background: none;
  border: none;
  color: #6b7280;
  font-size: 11px;
  cursor: pointer;
  text-decoration: underline;
  text-align: left;
  padding: 0;
}

.report-error {
  font-size: 12px;
  color: #f87171;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
```

- [ ] **Step 6: Verify TypeScript compiles clean**

```bash
cd apps/desktop && pnpm exec tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add apps/desktop/src/renderer/components/ArtifactsPanel.tsx apps/desktop/src/renderer/components/ArtifactsPanel.css
git commit -m "feat(artifacts): add deep research report generation UI with MD/PDF download"
```

---

### Task 4: Manual smoke test

**Files:** none (verification only)

- [ ] **Step 1: Start the app**

```bash
export OPENAI_API_KEY=<your key>
pnpm dev
```

Wait for both `[backend] Uvicorn running` and `[desktop] starting electron app` in the terminal.

- [ ] **Step 2: Trigger report generation**

1. Open the app, start a conversation with a few messages about a location
2. Open the Artifacts panel (right sidebar)
3. Confirm "Generate Report" button is visible at the top
4. Click "Generate Report"
5. Confirm the button disappears and the spinner + "Researching…" appears
6. Confirm search steps appear in the log as the model works (takes 1–3 minutes)
7. Confirm "✓ Report ready" with "Download .md" and "Download PDF" appears when done

- [ ] **Step 3: Test downloads**

1. Click "Download .md" — confirm a `.md` file downloads and opens with readable content
2. Click "Download PDF" — confirm a `.pdf` file downloads with proper headings and body text

- [ ] **Step 4: Test cancel**

1. Click "Generate Report" again
2. While running, click "Cancel"
3. Confirm UI resets to "Generate Report" button

- [ ] **Step 5: Commit if any fixes were needed**

```bash
git add -p
git commit -m "fix(reports): <describe any fix>"
```
