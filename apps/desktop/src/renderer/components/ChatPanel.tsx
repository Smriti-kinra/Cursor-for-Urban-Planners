import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'
import {
  ChatMessage,
  Conversation,
  MapContext,
  MapAction,
  ChatErrorMessage,
} from '../types'
import type { DocumentImage } from './DocumentView'
import './ChatPanel.css'

const SUGGESTION_POOL: string[] = [
  // GIS / spatial analysis
  "What's the total area of my polygons in hectares?",
  'Buffer the selected layer by 200 meters',
  'Compute the centroid of each polygon',
  // OSM data fetching
  'Find all hospitals within 2 km of the current view',
  'Show me schools and parks in this area',
  // Boundaries
  'Fetch the administrative boundary for this city',
  // Routing
  'Get a driving route between these two points',
  // Weather / climate
  "What's the historical rainfall here?",
  // Demographics
  'Pull population density for this region',
  // Zoning / planning workflows
  'Apply mixed-use zoning to the polygons in the south-east',
  'Highlight all R1 zones',
  // Web search
  'Search the web for transit-oriented development guidelines',
  // Document mode
  'Summarize the planning document I just opened',
]

function pickSuggestions(n: number): string[] {
  const shuffled = [...SUGGESTION_POOL].sort(() => Math.random() - 0.5)
  return shuffled.slice(0, Math.max(1, Math.min(n, shuffled.length)))
}

const BACKEND_WS = 'ws://localhost:8765/api/chat/ws'

// ── ResearchBubble ────────────────────────────────────────────────────────────

type ResearchPhase = 'idle' | 'running' | 'done'

interface ResearchBubbleProps {
  phase: 'running' | 'done'
  steps: string[]
  reasoning: string
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
  reasoning,
  markdown,
  citations,
  expanded,
  onToggleExpand,
  onDownloadMd,
  onDownloadPdf,
}: ResearchBubbleProps) {
  const stepsRef = useRef<HTMLDivElement>(null)
  const liveRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (stepsRef.current) {
      stepsRef.current.scrollTop = stepsRef.current.scrollHeight
    }
  }, [steps.length])

  // Keep the live report view pinned to the bottom as tokens stream in.
  useEffect(() => {
    if (phase === 'running' && liveRef.current) {
      liveRef.current.scrollTop = liveRef.current.scrollHeight
    }
  }, [markdown, reasoning, phase])

  return (
    <div className="research-bubble">
      <div className="research-bubble-header">
        {phase === 'running' ? (
          <>
            <span className="research-icon spinning">⟳</span>
            <span className="research-title">Deep Research</span>
            {steps.length > 0 && (
              <span className="research-count">{steps.length} searches</span>
            )}
          </>
        ) : (
          <>
            <span className="research-icon done">✓</span>
            <span className="research-title">Deep Research Complete</span>
            <span className="research-count">
              {steps.length} {steps.length === 1 ? 'search' : 'searches'}
            </span>
          </>
        )}
      </div>

      {steps.length > 0 && (
        <div className="research-steps" ref={stepsRef}>
          {steps.map((step, i) => {
            const isLast = i === steps.length - 1
            const isDone = phase === 'done' || !isLast
            const generic = /^web search #\d+$/.test(step)
            return (
              <div key={i} className={`research-step ${isDone ? 'done' : 'active'}`}>
                <span className="step-icon">{isDone ? '✓' : '⟳'}</span>
                <span className="step-text">
                  {generic ? 'Searching the web…' : `Searching: ${step}`}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Live view — reasoning + the report being written, streamed in. */}
      {phase === 'running' && (reasoning || markdown) && (
        <div className="research-live" ref={liveRef}>
          {reasoning && !markdown && (
            <p className="research-thinking">{reasoning}</p>
          )}
          {markdown && (
            <div className="research-full-report streaming">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                {markdown}
              </ReactMarkdown>
            </div>
          )}
        </div>
      )}

      {/* Nothing has streamed back yet — reassure the user it's working. */}
      {phase === 'running' && steps.length === 0 && !reasoning && !markdown && (
        <p className="research-thinking">
          Planning the research — searching the web and gathering sources. This can take a few minutes.
        </p>
      )}

      {phase === 'done' && markdown && (
        <div className="research-report">
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

interface ChatPanelProps {
  conversations: Conversation[]
  activeConversation: Conversation | null
  onCreateConversation: () => void
  onSelectConversation: (id: string) => void
  onDeleteConversation: (id: string) => void
  onMessagesChange: (messages: ChatMessage[]) => void
  mapContext: MapContext
  onMapAction: (action: MapAction) => void
  documentImage?: DocumentImage | null
  injectedMessage?: { text: string; nonce: number } | null
}

function CodePre({ children, ...props }: React.HTMLAttributes<HTMLPreElement>) {
  const preRef = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)

  return (
    <div className="code-block">
      <div className="code-block-header">
        <button
          className="code-copy-btn"
          onClick={() => {
            navigator.clipboard.writeText(preRef.current?.textContent || '')
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
          }}
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre ref={preRef} {...props}>
        {children}
      </pre>
    </div>
  )
}

export default function ChatPanel({
  conversations,
  activeConversation,
  onCreateConversation,
  onSelectConversation,
  onDeleteConversation,
  onMessagesChange,
  mapContext,
  onMapAction,
  documentImage,
  injectedMessage,
}: ChatPanelProps) {
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [toolStatus, setToolStatus] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([])
  const [currentModel, setCurrentModel] = useState<string>('')
  const [isSwitchingModel, setIsSwitchingModel] = useState(false)
  const [chatError, setChatError] = useState<ChatErrorMessage | null>(null)
  const [suggestions, setSuggestions] = useState<string[]>(() => pickSuggestions(3))

  // Deep research state
  const [researchPhase, setResearchPhase] = useState<ResearchPhase>('idle')
  const [researchSteps, setResearchSteps] = useState<string[]>([])
  const [researchMarkdown, setResearchMarkdown] = useState('')
  const [researchCitations, setResearchCitations] = useState<Array<{url: string; title: string}>>([])
  const [researchExpanded, setResearchExpanded] = useState(false)
  const [researchReasoning, setResearchReasoning] = useState('')
  const reportMdRef = useRef('')

  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pendingInputRef = useRef<string | null>(null)
  // Tracks the in-flight assistant message: its accumulator and the
  // message-list snapshot the stream is being appended to. The WS handler
  // is attached once and dispatches into this slot, so back-to-back sends
  // never cross-contaminate each other.
  const inFlightRef = useRef<{
    base: ChatMessage[]
    accum: string
    timestamp: number
  } | null>(null)
  // Whether the current WS connection has already received the history
  // replay payload. Reset whenever we open a fresh connection.
  const historySentRef = useRef(false)

  const messages = activeConversation?.messages ?? []
  const onMessagesChangeRef = useRef(onMessagesChange)
  onMessagesChangeRef.current = onMessagesChange
  const onMapActionRef = useRef(onMapAction)
  onMapActionRef.current = onMapAction

  useEffect(() => {
    if (activeConversation && pendingInputRef.current) {
      const pending = pendingInputRef.current
      pendingInputRef.current = null
      setInput(pending)
      setTimeout(() => {
        setInput('')
        sendMessageDirect(pending)
      }, 0)
    }
  }, [activeConversation?.id]) // eslint-disable-line react-hooks/exhaustive-deps

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

  useEffect(() => {
    Promise.all([
      window.electronAPI.getModels(),
      window.electronAPI.getCurrentModel(),
    ]).then(([models, model]) => {
      setAvailableModels(models)
      setCurrentModel(model)
    }).catch(() => { /* not in Electron context */ })
  }, [])

  const scrollToBottom = useCallback((): void => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(scrollToBottom, [messages, scrollToBottom])

  const handleWsMessage = useCallback((event: MessageEvent) => {
    let data: {
      type?: string
      content?: string
      tool?: string
      action?: string
      payload?: unknown
      code?: string
      message?: string
      query?: string
      delta?: string
      markdown?: string
      citations?: Array<{url: string; title: string}>
    }
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }
    if (data.type === 'stream') {
      const slot = inFlightRef.current
      if (!slot) return
      slot.accum += data.content || ''
      onMessagesChangeRef.current([
        ...slot.base,
        { role: 'assistant', content: slot.accum, timestamp: slot.timestamp },
      ])
    } else if (data.type === 'tool_use') {
      setToolStatus(`Using ${data.tool}...`)
    } else if (data.type === 'action' && data.action) {
      onMapActionRef.current({
        type: data.action,
        payload: (data.payload || {}) as never,
      } as MapAction)
    } else if (data.type === 'error') {
      setChatError({
        code: String(data.code || 'unknown'),
        message: String(data.message || 'Unknown error'),
      })
      // Treat error as terminal for the in-flight stream so the user can
      // send the next message; an `end` frame may or may not follow.
      setIsStreaming(false)
      setToolStatus(null)
      inFlightRef.current = null
    } else if (data.type === 'research_start') {
      setResearchPhase('running')
      setResearchSteps([])
      setResearchMarkdown('')
      setResearchCitations([])
      setResearchExpanded(false)
      setResearchReasoning('')
      reportMdRef.current = ''
      setToolStatus('Deep Research in progress…')
    } else if (data.type === 'research_step') {
      const q = data.query ?? ''
      if (q) setResearchSteps((prev) => [...prev, q])
    } else if (data.type === 'research_reasoning_delta') {
      const d = data.delta ?? ''
      if (d) setResearchReasoning((prev) => prev + d)
    } else if (data.type === 'research_text_delta') {
      const d = data.delta ?? ''
      if (d) {
        reportMdRef.current += d
        setResearchMarkdown((prev) => prev + d)
        setToolStatus(null)
      }
    } else if (data.type === 'research_heartbeat') {
      // keep-alive ping — no UI update needed
    } else if (data.type === 'research_report') {
      const md = data.markdown ?? ''
      reportMdRef.current = md
      setResearchMarkdown(md)
      if (data.citations && data.citations.length) setResearchCitations(data.citations)
      setResearchPhase('done')
      setToolStatus(null)
    } else if (data.type === 'research_done') {
      setResearchPhase((prev) => (prev !== 'done' ? 'done' : prev))
      setToolStatus(null)
    } else if (data.type === 'end') {
      setIsStreaming(false)
      setToolStatus(null)
      inFlightRef.current = null
    }
  }, [])

  const connectWebSocket = useCallback((): Promise<WebSocket> => {
    return new Promise((resolve, reject) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        resolve(wsRef.current)
        return
      }
      const ws = new WebSocket(BACKEND_WS)
      historySentRef.current = false
      ws.addEventListener('message', handleWsMessage)
      ws.addEventListener('open', () => {
        wsRef.current = ws
        resolve(ws)
      })
      ws.addEventListener('error', () =>
        reject(new Error('WebSocket connection failed')),
      )
      ws.addEventListener('close', () => {
        wsRef.current = null
        historySentRef.current = false
        setIsStreaming(false)
        setToolStatus(null)
        inFlightRef.current = null
      })
    })
  }, [handleWsMessage])

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
    const pageHeight = doc.internal.pageSize.getHeight()
    const margin = 48
    const maxLineWidth = pageWidth - margin * 2
    let y = margin

    const checkY = (needed: number) => {
      if (y + needed > pageHeight - margin) {
        doc.addPage()
        y = margin
      }
    }

    // Strip inline markdown to plain text for jsPDF's core fonts:
    // **bold**/__bold__ → bold, *italic*, `code`, [text](url) → text (url),
    // and leftover emphasis/escape markers.
    const stripInline = (s: string): string =>
      s
        .replace(/!\[[^\]]*\]\([^)]*\)/g, '')            // images → drop
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')  // links → text (url)
        .replace(/`([^`]+)`/g, '$1')                      // inline code
        .replace(/(\*\*|__)(.*?)\1/g, '$2')               // bold
        .replace(/(\*|_)(.*?)\1/g, '$2')                  // italic
        .replace(/~~(.*?)~~/g, '$2')                       // strikethrough
        .replace(/\\([\\`*_{}[\]()#+\-.!])/g, '$1')        // escaped chars

    const writeWrapped = (text: string, size: number, style: 'normal' | 'bold' | 'italic', lh: number, indent = 0) => {
      doc.setFontSize(size); doc.setFont('helvetica', style)
      const wrapped = doc.splitTextToSize(text, maxLineWidth - indent) as string[]
      for (const wl of wrapped) {
        checkY(lh); doc.text(wl, margin + indent, y); y += lh
      }
    }

    const lines = md.split('\n')
    for (let i = 0; i < lines.length; i++) {
      const raw = lines[i].replace(/\s+$/, '')
      const line = raw.trimStart()

      // Markdown table → render as a bordered grid of cells.
      const isTableRow = /^\|.*\|$/.test(line)
      if (isTableRow) {
        const rows: string[][] = []
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          const cells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((c) => stripInline(c.trim()))
          // Skip the |---|---| separator row.
          if (!cells.every((c) => /^:?-{2,}:?$/.test(c) || c === '')) rows.push(cells)
          i++
        }
        i-- // step back; outer loop will advance
        if (rows.length) {
          const cols = Math.max(...rows.map((r) => r.length))
          const colW = (maxLineWidth) / cols
          doc.setFontSize(9)
          for (let r = 0; r < rows.length; r++) {
            const isHeader = r === 0
            doc.setFont('helvetica', isHeader ? 'bold' : 'normal')
            // Measure tallest cell in the row for height.
            const cellLines = rows[r].map((c) => doc.splitTextToSize(c, colW - 8) as string[])
            const rowH = Math.max(14, ...cellLines.map((cl) => cl.length * 11 + 6))
            checkY(rowH)
            for (let c = 0; c < cols; c++) {
              const x = margin + c * colW
              doc.setDrawColor(200); doc.rect(x, y, colW, rowH)
              const cl = cellLines[c] || ['']
              cl.forEach((t, li) => doc.text(t, x + 4, y + 12 + li * 11))
            }
            y += rowH
          }
          y += 6
        }
        continue
      }

      if (line.startsWith('### ')) {
        y += 6; writeWrapped(stripInline(line.slice(4)), 13, 'bold', 17)
      } else if (line.startsWith('## ')) {
        y += 8; writeWrapped(stripInline(line.slice(3)), 16, 'bold', 21)
      } else if (line.startsWith('# ')) {
        y += 8; writeWrapped(stripInline(line.slice(2)), 20, 'bold', 27)
      } else if (/^>\s?/.test(line)) {
        writeWrapped(stripInline(line.replace(/^>\s?/, '')), 11, 'italic', 14, 16)
      } else if (/^(\s*)([-*+])\s+/.test(raw)) {
        const depth = (raw.match(/^\s*/)?.[0].length ?? 0) >= 2 ? 16 : 0
        writeWrapped('• ' + stripInline(line.replace(/^[-*+]\s+/, '')), 11, 'normal', 14, 12 + depth)
      } else if (/^\d+\.\s+/.test(line)) {
        writeWrapped(stripInline(line), 11, 'normal', 14, 12)
      } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
        checkY(12); doc.setDrawColor(220); doc.line(margin, y, pageWidth - margin, y); y += 12
      } else if (line === '') {
        y += 8
      } else {
        writeWrapped(stripInline(line), 11, 'normal', 14)
      }
    }
    doc.save(`urban-planning-report-${Date.now()}.pdf`)
  }, [])

  useEffect(() => {
    setResearchPhase('idle')
    setResearchSteps([])
    setResearchMarkdown('')
    setResearchCitations([])
    setResearchExpanded(false)
    setResearchReasoning('')
    reportMdRef.current = ''
  }, [activeConversation?.id])

  const sendMessageDirect = async (text: string): Promise<void> => {
    if (!text.trim() || isStreaming || !activeConversation) return

    const userMessage: ChatMessage = { role: 'user', content: text.trim(), timestamp: Date.now() }
    const updated: ChatMessage[] = [...messages, userMessage]
    const placeholderTs = Date.now() + 1
    onMessagesChange([
      ...updated,
      { role: 'assistant', content: '', timestamp: placeholderTs },
    ])
    setIsStreaming(true)
    setToolStatus(null)
    setChatError(null)

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }

    try {
      const ws = await connectWebSocket()
      inFlightRef.current = {
        base: updated,
        accum: '',
        timestamp: placeholderTs,
      }

      // First payload on a fresh connection ships the conversation history
      // so the backend can rebuild the OpenAI message list. Subsequent
      // payloads on the same connection carry only the new user message.
      // Document mode now bridges to the live map: send map_context too so
      // the model can fly_to / add markers / run GIS tools while looking at
      // the document. Backend accepts both fields in either mode.
      const payload: Record<string, unknown> = {
        content: userMessage.content,
        map_context: mapContext,
        image: documentImage
          ? { base64: documentImage.base64, mime_type: documentImage.mimeType }
          : undefined,
      }
      if (!historySentRef.current && messages.length > 0) {
        payload.history = messages.map((m) => ({
          role: m.role,
          content: m.content,
        }))
      }
      historySentRef.current = true

      ws.send(JSON.stringify(payload))
    } catch {
      setChatError({
        code: 'connection',
        message: 'Could not reach the backend. Is the server running on :8765?',
      })
      onMessagesChange(updated)
      setIsStreaming(false)
      inFlightRef.current = null
    }
  }

  const sendMessage = async (): Promise<void> => {
    if (!input.trim() || isStreaming) return

    if (!activeConversation) {
      pendingInputRef.current = input.trim()
      setInput('')
      onCreateConversation()
      return
    }

    const text = input.trim()
    setInput('')
    await sendMessageDirect(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 150) + 'px'
  }

  const handleNewChat = () => {
    wsRef.current?.close()
    wsRef.current = null
    setChatError(null)
    setSuggestions(pickSuggestions(3))
    onCreateConversation()
    setShowHistory(false)
  }

  const handleModelChange = async (modelId: string) => {
    if (modelId === currentModel || isSwitchingModel) return
    setIsSwitchingModel(true)
    try {
      const result = await window.electronAPI.switchModel(modelId)
      setCurrentModel(modelId)
      // Close the WS so the next message picks up the new model
      wsRef.current?.close()
      wsRef.current = null
      if (result.requiresManualRestart) {
        setToolStatus('Model updated — restart the app to apply')
        setTimeout(() => setToolStatus(null), 4000)
      }
    } finally {
      setIsSwitchingModel(false)
    }
  }

  const formatTime = (ts: number) => {
    const d = new Date(ts)
    const now = new Date()
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000)
    if (diffDays === 0) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return d.toLocaleDateString([], { weekday: 'short' })
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }

  return (
    <div className="chat-panel">
      {/* ── Chat header ── */}
      <div className="chat-header">
        <button
          className="chat-history-toggle"
          onClick={() => setShowHistory(!showHistory)}
          title="Chat history"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 3.5V8L11 10M14 8A6 6 0 1 1 2 8a6 6 0 0 1 12 0Z"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="chat-header-title">
            {activeConversation?.title || 'New chat'}
          </span>
          <svg
            className={`chat-chevron ${showHistory ? 'open' : ''}`}
            width="10"
            height="10"
            viewBox="0 0 10 10"
            fill="none"
          >
            <path d="M2.5 4L5 6.5L7.5 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
        <button className="chat-new-btn-header" onClick={handleNewChat} title="New chat">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path d="M8 3V13M3 8H13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {/* ── Conversation history dropdown ── */}
      {showHistory && (
        <div className="chat-history-list">
          {conversations.length === 0 ? (
            <div className="chat-history-empty">No conversations yet</div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={`chat-history-item ${conv.id === activeConversation?.id ? 'active' : ''}`}
                onClick={() => {
                  onSelectConversation(conv.id)
                  setShowHistory(false)
                  wsRef.current?.close()
                  wsRef.current = null
                }}
              >
                <div className="chat-history-item-content">
                  <span className="chat-history-item-title">{conv.title}</span>
                  <span className="chat-history-item-meta">
                    {conv.messages.length} msg{conv.messages.length !== 1 ? 's' : ''} &middot;{' '}
                    {formatTime(conv.createdAt)}
                  </span>
                </div>
                <button
                  className="chat-history-delete"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteConversation(conv.id)
                  }}
                  title="Delete conversation"
                >
                  &times;
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {/* ── Error banner ── */}
      {chatError && (
        <div className={`chat-error chat-error-${chatError.code}`} role="alert">
          <span className="chat-error-code">{chatError.code}</span>
          <span className="chat-error-msg">{chatError.message}</span>
          <button
            className="chat-error-dismiss"
            onClick={() => setChatError(null)}
            aria-label="Dismiss"
          >
            &times;
          </button>
        </div>
      )}

      {/* ── Messages area ── */}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-icon">&#10022;</div>
            <p className="chat-empty-title">Urban Planning Assistant</p>
            <p className="chat-empty-hint">
              Ask about zoning, land use, transportation, or spatial analysis. I can see your map
              layers and help with planning decisions.
            </p>
            <div className="chat-empty-suggestions">
              {suggestions.map((s) => (
                <span key={s} className="suggestion" onClick={() => setInput(s)}>
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => {
          // Don't render placeholder/empty assistant turns (e.g. a turn that
          // only called a tool like generate_report) — they show as a blank
          // "ASSISTANT" bubble. The research bubble below covers that case.
          if (msg.role === 'assistant' && !msg.content.trim()) return null
          return (
            <div key={i} className={`chat-msg ${msg.role}`}>
              <div className="chat-msg-role">{msg.role === 'user' ? 'You' : 'Assistant'}</div>
              <div className="chat-msg-body">
                {msg.role === 'assistant' ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeHighlight]}
                    components={{
                      pre: CodePre,
                    }}
                  >
                    {msg.content}
                  </ReactMarkdown>
                ) : (
                  <p>{msg.content}</p>
                )}
              </div>
            </div>
          )
        })}
        {researchPhase !== 'idle' && (
          <div className="chat-msg assistant">
            <div className="chat-msg-role">Assistant</div>
            <div className="chat-msg-body">
              <ResearchBubble
                phase={researchPhase}
                steps={researchSteps}
                reasoning={researchReasoning}
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
        {/* Tool status + streaming dots are hidden while a research run owns
            the screen — the ResearchBubble shows its own progress. */}
        {toolStatus && researchPhase === 'idle' && (
          <div className="chat-tool-status">
            <span className="tool-dot" />
            {toolStatus}
          </div>
        )}
        {isStreaming && !toolStatus && researchPhase === 'idle' && (
          <div className="chat-streaming">
            <span className="streaming-dot" />
            <span className="streaming-dot" />
            <span className="streaming-dot" />
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Input area ── */}
      <div className="chat-input-area">
        <div className="chat-input-row">
          <textarea
            ref={textareaRef}
            className="chat-input"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={
              activeConversation
                ? 'Ask anything about your project...'
                : 'Start a new conversation...'
            }
            rows={1}
          />
          <button
            className="chat-send-btn"
            onClick={sendMessage}
            disabled={!input.trim() || isStreaming}
            title="Send (Enter)"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M2.5 8H13.5M13.5 8L8.5 3M13.5 8L8.5 13"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
        <div className="chat-input-footer">
          {availableModels.length > 0 && (
            <select
              className="model-selector"
              value={currentModel}
              onChange={(e) => handleModelChange(e.target.value)}
              disabled={isSwitchingModel || isStreaming}
              title="Switch model"
            >
              {availableModels.map((m) => (
                <option key={m.id} value={m.id} disabled={m.locked}>
                  {m.locked ? '🔒 ' : ''}{m.name}
                </option>
              ))}
            </select>
          )}
          {isSwitchingModel ? (
            <span className="chat-hint-text">Switching model...</span>
          ) : (
            <span className="chat-hint-text">Enter to send, Shift+Enter for newline</span>
          )}
        </div>
      </div>
    </div>
  )
}
