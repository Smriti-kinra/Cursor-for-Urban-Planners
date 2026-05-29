# Deep Research In Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user asks to generate a report in chat, the backend detects the intent, runs `o4-mini-deep-research` with web search (10-minute cap), and streams every search step + the final report back through the existing WebSocket as typed messages that render live in ChatPanel.

**Architecture:** A new `generate_report` pseudo-tool is added to the regular agent's tool list. When the agent calls it, `_execute_tool` intercepts it, runs the Responses API streaming loop (reusing `_build_stream_prompt` + `STREAM_SYSTEM` from `reports.py`), and emits a sequence of new WebSocket message types: `research_step` (one per web search), `research_report` (final markdown + citations), and `research_done` (terminal). ChatPanel renders these inline: search steps as a live progress list inside a special assistant bubble, the final report as a collapsible markdown block with a download bar below it. Chat input stays disabled (via `isStreaming`) for the entire duration. The "Generate Report" button added in the previous plan is removed from ArtifactsPanel.

**Tech Stack:** Python `openai` Responses API (`client.responses.create(stream=True)`), FastAPI WebSocket, React `useState`/`useRef`, `jspdf` (already installed), existing `_build_stream_prompt` + `STREAM_SYSTEM` in `reports.py`.

---

## File Map

| File | Change |
|---|---|
| `packages/backend/routers/chat.py` | Add `generate_report` tool declaration + intercept in `_execute_tool`; import `_build_stream_prompt`, `STREAM_SYSTEM` from `reports.py`; add `_run_deep_research()` helper |
| `packages/backend/routers/reports.py` | Export `_build_stream_prompt` and `STREAM_SYSTEM` (already defined; just ensure importable) |
| `apps/desktop/src/renderer/components/ChatPanel.tsx` | Handle 3 new WS message types; render `ResearchBubble` inline in the message list |
| `apps/desktop/src/renderer/components/ChatPanel.css` | Style the research bubble, step list, report block, download bar |
| `apps/desktop/src/renderer/components/ArtifactsPanel.tsx` | Remove the "Generate Report" button and all report generation state/functions added in the previous plan |
| `apps/desktop/src/renderer/components/ArtifactsPanel.css` | Remove all `.report-*` CSS classes added in previous plan |
| `apps/desktop/src/renderer/App.tsx` | Remove `chatHistory` and `mapContext` props from `<ArtifactsPanel>` |

---

### Task 1: Add `_run_deep_research()` to chat.py and wire the `generate_report` tool

**Files:**
- Modify: `packages/backend/routers/chat.py`
- Modify: `packages/backend/routers/reports.py` (make `_build_stream_prompt` importable)

**Background:** `reports.py` already defines `_build_stream_prompt(request: ReportRequest)` and `STREAM_SYSTEM`. We need to call them from `chat.py`. The cleanest approach is to extract a plain-function version that takes the raw dicts (not the Pydantic model) so we don't need to import `ReportRequest`. We'll add a `_build_research_prompt` helper directly in `chat.py` that mirrors `_build_stream_prompt` but accepts raw dicts.

`chat.py` already imports `AsyncOpenAI` and has `_client`. We add a new async helper `_run_deep_research(messages, ws)` that:
1. Sends `research_start` WS message
2. Calls `_client.responses.create(model="o4-mini-deep-research", ..., stream=True)`
3. For each `response.web_search_call.searching` event → sends `research_step` WS message
4. For `response.output_text.done` → sends `research_report` WS message (markdown + empty annotations list)
5. On completion sends `research_done`
6. On exception sends `error`

Then we add a `generate_report` function tool to `_build_tools()` and intercept it in `_execute_tool`.

- [ ] **Step 1: Add `_RESEARCH_SYSTEM` constant and `_build_research_prompt` helper in chat.py**

Open `packages/backend/routers/chat.py`. After the `SYSTEM_PROMPT` constant (around line 146), add:

```python
# ── Deep research helpers ──────────────────────────────────────────────────────

_RESEARCH_SYSTEM = (
    "You are a professional urban planning report writer. "
    "Generate a well-structured, data-driven report in clean Markdown. "
    "Use the provided conversation, map data, and artifacts as your primary source. "
    "Enrich your analysis with publicly available information about the location. "
    "Respond ONLY with the Markdown report. Always respond in English."
)

_RESEARCH_REPORT_TEMPLATE = """Generate a comprehensive urban planning report based on the data below.

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


def _build_research_prompt(messages: list[dict], map_context: dict | None) -> str:
    """Build the deep research prompt from conversation history and map context."""
    parts = [_RESEARCH_REPORT_TEMPLATE]

    if map_context:
        center = map_context.get("center", [])
        zoom = map_context.get("zoom", "")
        bounds = map_context.get("bounds", {})
        basemap = map_context.get("basemap", "")
        bookmarks = map_context.get("bookmarks", [])
        layers = map_context.get("layers", [])

        loc_lines = [f"**Center:** {center}", f"**Zoom:** {zoom}", f"**Basemap:** {basemap}"]
        if bounds:
            loc_lines.append(
                f"**Bounds:** W={bounds.get('west')}, S={bounds.get('south')}, "
                f"E={bounds.get('east')}, N={bounds.get('north')}"
            )
        parts.append("## Map Context\n" + "\n".join(loc_lines))

        if bookmarks:
            bm_lines = [
                f"- {b.get('name', '')}: bounds W={b.get('west')}, S={b.get('south')}, "
                f"E={b.get('east')}, N={b.get('north')}"
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

    # Include conversation (skip system messages and tool messages)
    conv_lines = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "user" and isinstance(content, str) and content.strip():
            conv_lines.append(f"**User:** {content}")
        elif role == "assistant" and isinstance(content, str) and content.strip():
            conv_lines.append(f"**Assistant:** {content}")
    if conv_lines:
        parts.append("## Conversation\n" + "\n\n".join(conv_lines))

    return "\n\n".join(parts)
```

- [ ] **Step 2: Add `_run_deep_research()` async helper in chat.py**

Immediately after `_build_research_prompt`, add:

```python
async def _run_deep_research(messages: list[dict], map_context: dict | None, ws: WebSocket) -> str:
    """Run o4-mini-deep-research and stream progress back over the WebSocket.

    Sends these WS message types:
      research_start  — emitted once before the API call
      research_step   — one per web search (query string)
      research_report — final markdown text + citations list
      research_done   — terminal signal

    Returns a short result string for the tool message inserted into history.
    """
    await ws.send_text(json.dumps({"type": "research_start"}))

    prompt = _build_research_prompt(messages, map_context)

    try:
        got_text = False
        async with await _client.responses.create(
            model="o4-mini-deep-research",
            input=prompt,
            instructions=_RESEARCH_SYSTEM,
            tools=[{"type": "web_search_preview"}],
            max_tool_calls=30,
            stream=True,
        ) as stream:
            async for event in stream:
                event_type = getattr(event, "type", None)

                if event_type == "response.web_search_call.searching":
                    query = getattr(event, "query", "") or ""
                    if query:
                        await ws.send_text(json.dumps({
                            "type": "research_step",
                            "query": query,
                        }))

                elif event_type == "response.output_text.done":
                    text = getattr(event, "text", "") or ""
                    if text:
                        got_text = True
                        # Extract annotations if present (citations)
                        annotations = []
                        for item in getattr(event, "annotations", None) or []:
                            url = getattr(item, "url", None)
                            title = getattr(item, "title", None)
                            if url:
                                annotations.append({"url": url, "title": title or url})
                        await ws.send_text(json.dumps({
                            "type": "research_report",
                            "markdown": text,
                            "citations": annotations,
                        }))

        if not got_text:
            await ws.send_text(json.dumps({
                "type": "error",
                "code": "research_empty",
                "message": "Deep research completed but produced no report text.",
            }))
            return json.dumps({"error": "No report text produced."})

        await ws.send_text(json.dumps({"type": "research_done"}))
        return json.dumps({"status": "report_generated"})

    except Exception as exc:
        await ws.send_text(json.dumps({
            "type": "error",
            "code": "research_error",
            "message": str(exc),
        }))
        return json.dumps({"error": str(exc)})
```

- [ ] **Step 3: Add `generate_report` tool declaration to `_build_tools()`**

Find `_build_tools()`. At the very end of the function, just before `return tools`, add:

```python
    # Deep research report generation
    tools.append(_decl_to_openai(
        "generate_report",
        (
            "Generate a comprehensive urban planning research report for the current project. "
            "Use this when the user asks to generate a report, create a report, write a planning report, "
            "or produce a deep research analysis. The report uses web search to enrich the analysis "
            "with current public data. This takes several minutes."
        ),
        {"type": "object", "properties": {}, "required": []},
    ))
```

- [ ] **Step 4: Intercept `generate_report` in `_execute_tool`**

The `_execute_tool` function signature is:
```python
async def _execute_tool(name: str, args: dict, ws: WebSocket) -> str:
```

But it doesn't have access to `messages` or `map_context`. We need to pass them. Change the signature of `_execute_tool` to accept optional context:

Find:
```python
async def _execute_tool(name: str, args: dict, ws: WebSocket) -> str:
    if name in _ACTION_TOOLS:
```

Replace with:
```python
async def _execute_tool(
    name: str,
    args: dict,
    ws: WebSocket,
    messages: list[dict] | None = None,
    map_context: dict | None = None,
) -> str:
    if name == "generate_report":
        return await _run_deep_research(messages or [], map_context, ws)

    if name in _ACTION_TOOLS:
```

- [ ] **Step 5: Pass `messages` and `map_context` to `_execute_tool` from `_run_agent`**

`_run_agent` already has `messages` in scope. We need to thread `map_context` into it too. Change `_run_agent`'s signature:

Find:
```python
async def _run_agent(messages: list[dict], ws: WebSocket, tools: list[dict] | None = None) -> None:
```

Replace with:
```python
async def _run_agent(
    messages: list[dict],
    ws: WebSocket,
    tools: list[dict] | None = None,
    map_context: dict | None = None,
) -> None:
```

Then find the `_execute_tool` call inside `_run_agent`:
```python
                result_str = await _execute_tool(tool_name, args, ws)
```

Replace with:
```python
                result_str = await _execute_tool(tool_name, args, ws, messages=messages, map_context=map_context)
```

- [ ] **Step 6: Pass `map_context` through from the WebSocket handler to `_run_agent`**

In `chat_websocket`, find:
```python
            await _run_agent(full_messages, websocket, tools=tools)
```

Replace with:
```python
            await _run_agent(full_messages, websocket, tools=tools, map_context=map_context)
```

- [ ] **Step 7: Mention `generate_report` in SYSTEM_PROMPT**

Find in `SYSTEM_PROMPT`:
```python
    "- Artifacts: create_artifact (format: markdown/table/geojson), list_artifacts, get_artifact\n"
    "  Re-adding geometry: call get_artifact to retrieve a geojson artifact's content, then pass it to add_geojson.\n\n"
```

Replace with:
```python
    "- Artifacts: create_artifact (format: markdown/table/geojson), list_artifacts, get_artifact\n"
    "  Re-adding geometry: call get_artifact to retrieve a geojson artifact's content, then pass it to add_geojson.\n"
    "- Reports: generate_report — generates a deep research urban planning report using web search. "
    "Use when user asks to generate/create/write a report or planning analysis.\n\n"
```

- [ ] **Step 8: Verify backend imports cleanly**

```bash
cd /Users/Utkarsh/Desktop/Projects/Cursor\ for\ Urban\ Planners/packages/backend && source .buildenv/bin/activate && python -c "from routers.chat import chat_websocket; print('OK')"
```

Expected: `OK`

- [ ] **Step 9: Commit**

```bash
cd /Users/Utkarsh/Desktop/Projects/Cursor\ for\ Urban\ Planners
git add packages/backend/routers/chat.py
git commit -m "feat(chat): add generate_report tool with o4-mini-deep-research streaming"
```

---

### Task 2: Handle new WS message types in ChatPanel and render ResearchBubble

**Files:**
- Modify: `apps/desktop/src/renderer/components/ChatPanel.tsx`
- Modify: `apps/desktop/src/renderer/components/ChatPanel.css`

**Background:** Three new WS message types need handling:
- `research_start` — sets a new "research mode" state, clears any previous research data
- `research_step` — appends a search query string to a list of steps shown live  
- `research_report` — stores final markdown + citations, transitions to "done" state
- `research_done` — terminal (same as `end` for streaming purposes)

These are rendered as a special `ResearchBubble` component inline in the message list — it appears while `isStreaming` is true and the research state is active. It shows:

**While running:**
```
🔍 Deep Research
  ✓ Searching: zoning regulations Austin TX
  ⟳ Searching: transit infrastructure downtown Austin   ← current (spinning)
```

**When done:**
```
✓ Deep Research Complete   (10 searches)

[report summary — first 3 lines of the markdown]

▼ View full report         [Download .md]  [Download PDF]
  (collapsible full markdown)
  
Sources: [Title1](url1)  [Title2](url2) ...
```

The `ResearchBubble` is NOT a separate component file — it's a small inline function component defined at the top of `ChatPanel.tsx`. It receives props from the parent state.

- [ ] **Step 1: Add research state variables to ChatPanel**

After the existing `useState` declarations in `ChatPanel`, add:

```tsx
  // Deep research state
  type ResearchPhase = 'idle' | 'running' | 'done'
  const [researchPhase, setResearchPhase] = useState<ResearchPhase>('idle')
  const [researchSteps, setResearchSteps] = useState<string[]>([])
  const [researchMarkdown, setResearchMarkdown] = useState('')
  const [researchCitations, setResearchCitations] = useState<Array<{url: string; title: string}>>([])
  const [researchExpanded, setResearchExpanded] = useState(false)
  const reportMdRef = useRef('')
```

Also add `useRef` to the React import if not already there. The current import is:
```tsx
import { useState, useEffect, useCallback } from 'react'
```
Replace with:
```tsx
import { useState, useEffect, useCallback, useRef } from 'react'
```
(Note: `useRef` may already be imported — check first and only add if missing.)

- [ ] **Step 2: Handle the new WS message types in `handleWsMessage`**

Find the `handleWsMessage` callback. After the `} else if (data.type === 'end') {` block, add handling for the new types. The full updated callback (showing the additions in context):

Find:
```tsx
    } else if (data.type === 'end') {
      setIsStreaming(false)
      setToolStatus(null)
      inFlightRef.current = null
    }
```

Replace with:
```tsx
    } else if (data.type === 'research_start') {
      setResearchPhase('running')
      setResearchSteps([])
      setResearchMarkdown('')
      setResearchCitations([])
      setResearchExpanded(false)
      reportMdRef.current = ''
      setToolStatus('Deep Research in progress…')
    } else if (data.type === 'research_step') {
      const q = (data as { query?: string }).query ?? ''
      if (q) setResearchSteps((prev) => [...prev, q])
    } else if (data.type === 'research_report') {
      const d = data as { markdown?: string; citations?: Array<{url: string; title: string}> }
      const md = d.markdown ?? ''
      reportMdRef.current = md
      setResearchMarkdown(md)
      setResearchCitations(d.citations ?? [])
      setResearchPhase('done')
      setToolStatus(null)
    } else if (data.type === 'research_done') {
      setResearchPhase('done')
      setToolStatus(null)
    } else if (data.type === 'end') {
      setIsStreaming(false)
      setToolStatus(null)
      inFlightRef.current = null
    }
```

Note: the `data` type annotation in `handleWsMessage` needs extending. Find the existing type:
```tsx
    let data: {
      type?: string
      content?: string
      tool?: string
      action?: string
      payload?: unknown
      code?: string
      message?: string
    }
```

Replace with:
```tsx
    let data: {
      type?: string
      content?: string
      tool?: string
      action?: string
      payload?: unknown
      code?: string
      message?: string
      query?: string
      markdown?: string
      citations?: Array<{url: string; title: string}>
    }
```

- [ ] **Step 3: Add download helpers for the research report**

After the existing `connectWebSocket` function, add:

```tsx
  const downloadResearchMd = useCallback(() => {
    const md = reportMdRef.current
    if (!md) return
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `urban-planning-report-${Date.now()}.md`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 150)
  }, [])

  const downloadResearchPdf = useCallback(async () => {
    const md = reportMdRef.current
    if (!md) return
    const { jsPDF } = await import('jspdf')
    const doc = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' })
    const pageWidth = doc.internal.pageSize.getWidth()
    const margin = 48
    const maxLineWidth = pageWidth - margin * 2
    let y = margin

    const checkY = (needed: number) => {
      if (y + needed > doc.internal.pageSize.getHeight() - margin) {
        doc.addPage()
        y = margin
      }
    }

    for (const rawLine of md.split('\n')) {
      const line = rawLine.trimEnd()
      if (line.startsWith('# ')) {
        checkY(28); doc.setFontSize(20); doc.setFont('helvetica', 'bold')
        doc.text(line.slice(2), margin, y); y += 28
      } else if (line.startsWith('## ')) {
        checkY(22); doc.setFontSize(16); doc.setFont('helvetica', 'bold')
        doc.text(line.slice(3), margin, y); y += 22
      } else if (line.startsWith('### ')) {
        checkY(18); doc.setFontSize(13); doc.setFont('helvetica', 'bold')
        doc.text(line.slice(4), margin, y); y += 18
      } else if (line === '') {
        y += 8
      } else {
        doc.setFontSize(11); doc.setFont('helvetica', 'normal')
        const wrapped = doc.splitTextToSize(line.replace(/^\s*[-*]\s+/, '• '), maxLineWidth)
        for (const wl of wrapped) {
          checkY(14); doc.text(wl, margin, y); y += 14
        }
      }
    }
    doc.save(`urban-planning-report-${Date.now()}.pdf`)
  }, [])
```

- [ ] **Step 4: Add the ResearchBubble inline component definition**

At the top of `ChatPanel.tsx`, after the imports and before the `ChatPanel` function definition, add:

```tsx
// ── ResearchBubble ────────────────────────────────────────────────────────────

interface ResearchBubbleProps {
  phase: 'running' | 'done'
  steps: string[]
  markdown: string
  citations: Array<{url: string; title: string}>
  expanded: boolean
  onToggleExpand: () => void
  onDownloadMd: () => void
  onDownloadPdf: () => void
}

function ResearchBubble({
  phase,
  steps,
  markdown,
  citations,
  expanded,
  onToggleExpand,
  onDownloadMd,
  onDownloadPdf,
}: ResearchBubbleProps) {
  const summaryLines = markdown.split('\n').filter(Boolean).slice(0, 3)

  return (
    <div className="research-bubble">
      <div className="research-bubble-header">
        {phase === 'running' ? (
          <>
            <span className="research-icon spinning">⟳</span>
            <span className="research-title">Deep Research</span>
          </>
        ) : (
          <>
            <span className="research-icon done">✓</span>
            <span className="research-title">Deep Research Complete</span>
            <span className="research-count">{steps.length} searches</span>
          </>
        )}
      </div>

      <div className="research-steps">
        {steps.map((step, i) => {
          const isLast = i === steps.length - 1
          const isDone = phase === 'done' || !isLast
          return (
            <div key={i} className={`research-step ${isDone ? 'done' : 'active'}`}>
              <span className="step-icon">{isDone ? '✓' : '⟳'}</span>
              <span className="step-text">Searching: {step}</span>
            </div>
          )
        })}
      </div>

      {phase === 'done' && markdown && (
        <div className="research-report">
          <div className="research-summary">
            {summaryLines.map((line, i) => (
              <p key={i} className="summary-line">{line.replace(/^#+\s*/, '')}</p>
            ))}
          </div>

          <div className="research-actions">
            <button className="research-toggle" onClick={onToggleExpand}>
              {expanded ? '▲ Hide full report' : '▼ View full report'}
            </button>
            <button className="research-dl-btn" onClick={onDownloadMd}>Download .md</button>
            <button className="research-dl-btn pdf" onClick={onDownloadPdf}>Download PDF</button>
          </div>

          {expanded && (
            <div className="research-full-report">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                {markdown}
              </ReactMarkdown>
            </div>
          )}

          {citations.length > 0 && (
            <div className="research-citations">
              <span className="citations-label">Sources:</span>
              {citations.map((c, i) => (
                <a key={i} href={c.url} target="_blank" rel="noreferrer" className="citation-link">
                  {c.title || c.url}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

Check that `ReactMarkdown`, `remarkGfm`, and `rehypeHighlight` are already imported at the top of `ChatPanel.tsx`. They are (from the existing message rendering). No new imports needed.

- [ ] **Step 5: Render ResearchBubble in the message list JSX**

Find in the JSX the closing of the messages list and the `toolStatus` block. The pattern looks like:

```tsx
        {toolStatus && (
          <div className="chat-tool-status">
```

Just before that block, add the ResearchBubble render:

```tsx
        {researchPhase !== 'idle' && (
          <div className="chat-message assistant">
            <div className="chat-message-content">
              <ResearchBubble
                phase={researchPhase as 'running' | 'done'}
                steps={researchSteps}
                markdown={researchMarkdown}
                citations={researchCitations}
                expanded={researchExpanded}
                onToggleExpand={() => setResearchExpanded((v) => !v)}
                onDownloadMd={downloadResearchMd}
                onDownloadPdf={downloadResearchPdf}
              />
            </div>
          </div>
        )}
        {toolStatus && (
```

- [ ] **Step 6: Reset research state when a new conversation starts**

Find the `useEffect` or logic that clears state when `activeConversation` changes. In `ChatPanel.tsx` look for the `useEffect` on `activeConversation`:

Search for: `useEffect` that references `activeConversation`. If one exists that resets state, add the research reset inside it. If no such effect exists, add one:

```tsx
  useEffect(() => {
    setResearchPhase('idle')
    setResearchSteps([])
    setResearchMarkdown('')
    setResearchCitations([])
    setResearchExpanded(false)
    reportMdRef.current = ''
  }, [activeConversation?.id])
```

- [ ] **Step 7: Add CSS for the research bubble**

Append to `apps/desktop/src/renderer/components/ChatPanel.css`:

```css
/* ── Research Bubble ─────────────────────────────────────────────────────── */

.research-bubble {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 0;
}

.research-bubble-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 13px;
}

.research-icon {
  font-size: 14px;
}

.research-icon.spinning {
  display: inline-block;
  animation: research-spin 1s linear infinite;
}

@keyframes research-spin {
  to { transform: rotate(360deg); }
}

.research-icon.done {
  color: #4ade80;
}

.research-title {
  color: #e2e8f0;
}

.research-count {
  font-size: 11px;
  color: #6b7280;
  font-weight: 400;
}

.research-steps {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-height: 180px;
  overflow-y: auto;
  padding-left: 2px;
}

.research-step {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.4;
}

.research-step.done .step-icon {
  color: #4ade80;
  flex-shrink: 0;
}

.research-step.active {
  color: #e2e8f0;
}

.research-step.active .step-icon {
  display: inline-block;
  animation: research-spin 1s linear infinite;
  flex-shrink: 0;
}

.step-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.research-report {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 4px;
}

.research-summary {
  background: rgba(255,255,255,0.04);
  border-left: 3px solid #3b82f6;
  padding: 8px 10px;
  border-radius: 0 4px 4px 0;
}

.summary-line {
  font-size: 12px;
  color: #d1d5db;
  margin: 0;
  line-height: 1.5;
}

.research-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.research-toggle {
  background: none;
  border: none;
  color: #60a5fa;
  font-size: 12px;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
}

.research-dl-btn {
  padding: 4px 10px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  background: #374151;
  color: #e2e8f0;
}

.research-dl-btn.pdf {
  background: #1d4ed8;
  color: #fff;
}

.research-dl-btn:hover { opacity: 0.85; }

.research-full-report {
  max-height: 480px;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.6;
  border-top: 1px solid rgba(255,255,255,0.08);
  padding-top: 10px;
}

.research-citations {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  border-top: 1px solid rgba(255,255,255,0.08);
  padding-top: 8px;
}

.citations-label {
  color: #6b7280;
  font-weight: 600;
}

.citation-link {
  color: #60a5fa;
  text-decoration: none;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.citation-link:hover {
  text-decoration: underline;
}
```

- [ ] **Step 8: Verify TypeScript compiles clean**

```bash
cd /Users/Utkarsh/Desktop/Projects/Cursor\ for\ Urban\ Planners/apps/desktop && pnpm exec tsc -p tsconfig.web.json --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
cd /Users/Utkarsh/Desktop/Projects/Cursor\ for\ Urban\ Planners
git add apps/desktop/src/renderer/components/ChatPanel.tsx apps/desktop/src/renderer/components/ChatPanel.css
git commit -m "feat(chat): render deep research steps and report inline in chat"
```

---

### Task 3: Remove the ArtifactsPanel report generation added in previous plan

**Files:**
- Modify: `apps/desktop/src/renderer/components/ArtifactsPanel.tsx`
- Modify: `apps/desktop/src/renderer/components/ArtifactsPanel.css`
- Modify: `apps/desktop/src/renderer/App.tsx`

**Background:** The previous plan added a "Generate Report" button, report state, and CSS to ArtifactsPanel. This task removes all of it since report generation now happens through chat. Also remove the `chatHistory` and `mapContext` props that were added to support it.

- [ ] **Step 1: Remove report generation code from ArtifactsPanel.tsx**

Read `apps/desktop/src/renderer/components/ArtifactsPanel.tsx` first. Remove:

1. The `useRef` from the React import (only if `useRef` is not used anywhere else in the file after the removal — check first)
2. The `ChatMessage` and `MapContext` type imports from `'../types'` (only `Artifact` should remain)
3. The two props `chatHistory` and `mapContext` from `ArtifactsPanelProps`
4. The `chatHistory = []` and `mapContext` destructuring from the component signature
5. The `type ReportPhase` declaration and all five report `useState`/`useRef` declarations
6. The `generateReport`, `cancelReport`, `downloadMd`, `downloadPdf` callback functions
7. The entire `{/* Report generation section */}` JSX block (the `<div className="report-section">` and everything inside it)

After removal the component signature should be back to:
```tsx
export default function ArtifactsPanel({ revision, onAddToMap }: ArtifactsPanelProps) {
```

And the props interface:
```tsx
interface ArtifactsPanelProps {
  revision?: number
  onAddToMap: (geojson: object, name: string) => void
}
```

- [ ] **Step 2: Remove report CSS from ArtifactsPanel.css**

Remove everything from `/* Report generation */` onwards in `ArtifactsPanel.css`. This is all the CSS added in the previous plan (`.report-section`, `.generate-report-btn`, `.report-progress`, etc.).

- [ ] **Step 3: Remove chatHistory and mapContext props from ArtifactsPanel in App.tsx**

Find:
```tsx
<ArtifactsPanel
  revision={artifactsRevision}
  chatHistory={activeConversation?.messages ?? []}
  mapContext={mapContext}
  onAddToMap={(geojson, name) => {
```

Replace with:
```tsx
<ArtifactsPanel
  revision={artifactsRevision}
  onAddToMap={(geojson, name) => {
```

- [ ] **Step 4: Verify TypeScript compiles clean**

```bash
cd /Users/Utkarsh/Desktop/Projects/Cursor\ for\ Urban\ Planners/apps/desktop && pnpm exec tsc -p tsconfig.web.json --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/Utkarsh/Desktop/Projects/Cursor\ for\ Urban\ Planners
git add apps/desktop/src/renderer/components/ArtifactsPanel.tsx apps/desktop/src/renderer/components/ArtifactsPanel.css apps/desktop/src/renderer/App.tsx
git commit -m "refactor(artifacts): remove report generation — moved to chat"
```
