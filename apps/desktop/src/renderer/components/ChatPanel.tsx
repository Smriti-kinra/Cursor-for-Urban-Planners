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
import appIcon from '../assets/icon.png'
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
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={headingComponents}
              >
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
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={headingComponents}
              >
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
  onRenameConversation?: (id: string, title: string) => void
  mapContext: MapContext
  onMapAction: (action: MapAction) => void
  documentImage?: DocumentImage | null
  injectedMessage?: { text: string; nonce: number } | null
  onComposeMapFigure?: (title: string) => HTMLCanvasElement | null
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

const getSlug = (node: any): string => {
  if (!node) return ''
  if (typeof node === 'string') {
    return node
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/(^-|-$)/g, '')
  }
  if (Array.isArray(node)) {
    return node.map(getSlug).join('-').replace(/-+/g, '-').replace(/(^-|-$)/g, '')
  }
  if (node.props && node.props.children) {
    return getSlug(node.props.children)
  }
  return ''
}

const headingComponents = {
  h1: ({ children, ...props }: any) => <h1 id={getSlug(children)} {...props}>{children}</h1>,
  h2: ({ children, ...props }: any) => <h2 id={getSlug(children)} {...props}>{children}</h2>,
  h3: ({ children, ...props }: any) => <h3 id={getSlug(children)} {...props}>{children}</h3>,
  h4: ({ children, ...props }: any) => <h4 id={getSlug(children)} {...props}>{children}</h4>,
  h5: ({ children, ...props }: any) => <h5 id={getSlug(children)} {...props}>{children}</h5>,
  h6: ({ children, ...props }: any) => <h6 id={getSlug(children)} {...props}>{children}</h6>,
}

export default function ChatPanel({
  conversations,
  activeConversation,
  onCreateConversation,
  onSelectConversation,
  onDeleteConversation,
  onMessagesChange,
  onRenameConversation,
  mapContext,
  onMapAction,
  documentImage,
  injectedMessage,
  onComposeMapFigure,
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

  // API Key State
  const [apiKey, setApiKey] = useState('')
  const [showApiKeyInput, setShowApiKeyInput] = useState(false)
  const [isSavingKey, setIsSavingKey] = useState(false)
  const [keyError, setKeyError] = useState<string | null>(null)
  const [keySuccess, setKeySuccess] = useState(false)
  const [isKeyLoaded, setIsKeyLoaded] = useState(false)

  // Conversation renaming state
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')

  // Google Maps API Key State
  const [googleKey, setGoogleKey] = useState('')
  const [isSavingGoogleKey, setIsSavingGoogleKey] = useState(false)
  const [googleKeyError, setGoogleKeyError] = useState<string | null>(null)
  const [googleKeySuccess, setGoogleKeySuccess] = useState(false)

  // Deep research state
  const [researchPhase, setResearchPhase] = useState<ResearchPhase>('idle')
  const [researchSteps, setResearchSteps] = useState<string[]>([])
  const [researchMarkdown, setResearchMarkdown] = useState('')
  const [researchCitations, setResearchCitations] = useState<Array<{url: string; title: string}>>([])
  const [researchExpanded, setResearchExpanded] = useState(false)
  const [researchReasoning, setResearchReasoning] = useState('')
  const reportMdRef = useRef('')
  const headerContainerRef = useRef<HTMLDivElement>(null)
  const historyBtnRef = useRef<HTMLButtonElement>(null)
  const historyListRef = useRef<HTMLDivElement>(null)

  // Close history list when clicking outside
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (
        showHistory &&
        historyListRef.current &&
        !historyListRef.current.contains(e.target as Node) &&
        historyBtnRef.current &&
        !historyBtnRef.current.contains(e.target as Node)
      ) {
        setShowHistory(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [showHistory])


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
    research?: {
      phase: 'idle' | 'running' | 'done'
      steps: string[]
      reasoning: string
      markdown: string
      citations: Array<{ url: string; title: string }>
    }
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
    window.electronAPI.getAPIKey()
      .then((key) => {
        setApiKey(key || '')
        setIsKeyLoaded(true)
        if (!key) {
          setShowApiKeyInput(true)
        }
      })
      .catch((err) => {
        console.error('Failed to load API key from secure storage:', err)
        setIsKeyLoaded(true)
        setShowApiKeyInput(true)
      })

    window.electronAPI.getGoogleMapsKey()
      .then((key) => {
        setGoogleKey(key || '')
      })
      .catch((err) => {
        console.error('Failed to load Google Maps API key:', err)
      })
  }, [])

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

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (headerContainerRef.current && !headerContainerRef.current.contains(e.target as Node)) {
        setShowHistory(false)
        setShowApiKeyInput(false)
      }
    }
    window.addEventListener('click', handleOutsideClick, true)
    return () => {
      window.removeEventListener('click', handleOutsideClick, true)
    }
  }, [])

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
      const msg = String(data.message || 'Unknown error')
      const lower = msg.toLowerCase()
      // Suppress noisy concurrency recv error when the user stops the run.
      if (lower.includes('cannot call recv') || lower.includes('another coroutine is already') || lower.includes('recv while')) {
        // Ignore this error as it originates from a cancelled/closed connection.
      } else {
        setChatError({
          code: String(data.code || 'unknown'),
          message: msg,
        })
      }
      // Treat error as terminal for the in-flight stream so the user can
      // send the next message; an `end` frame may or may not follow.
      setIsStreaming(false)
      setToolStatus(null)
      inFlightRef.current = null
    } else if (data.type === 'research_start') {
      const slot = inFlightRef.current
      if (slot) {
        slot.research = {
          phase: 'running',
          steps: [],
          reasoning: '',
          markdown: '',
          citations: []
        }
        onMessagesChangeRef.current([
          ...slot.base,
          { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
        ])
      }
      setToolStatus('Deep Research in progress…')
    } else if (data.type === 'research_step') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        const q = data.query ?? ''
        if (q) {
          slot.research.steps = [...slot.research.steps, q]
          onMessagesChangeRef.current([
            ...slot.base,
            { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
          ])
        }
      }
    } else if (data.type === 'research_reasoning_delta') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        const d = data.delta ?? ''
        if (d) {
          slot.research.reasoning += d
          onMessagesChangeRef.current([
            ...slot.base,
            { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
          ])
        }
      }
    } else if (data.type === 'research_text_delta') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        const d = data.delta ?? ''
        if (d) {
          slot.research.markdown += d
          onMessagesChangeRef.current([
            ...slot.base,
            { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
          ])
        }
      }
      setToolStatus(null)
    } else if (data.type === 'research_heartbeat') {
      // keep-alive ping — no UI update needed
    } else if (data.type === 'research_report') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        const md = data.markdown ?? ''
        slot.research.markdown = md
        slot.research.citations = data.citations || []
        slot.research.phase = 'done'
        onMessagesChangeRef.current([
          ...slot.base,
          { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
        ])
      }
      setToolStatus(null)
    } else if (data.type === 'research_done') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        slot.research.phase = 'done'
        onMessagesChangeRef.current([
          ...slot.base,
          { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
        ])
      }
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

  const handleStopStreaming = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }))
    }
    const slot = inFlightRef.current
    if (slot) {
      if (slot.research) {
        if (slot.research.markdown || slot.research.steps.length > 0) {
          slot.research.phase = 'done'
          onMessagesChange([
            ...slot.base,
            { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
          ])
        } else {
          onMessagesChange(slot.base)
        }
      } else if (slot.accum) {
        onMessagesChange([
          ...slot.base,
          { role: 'assistant', content: slot.accum, timestamp: slot.timestamp },
        ])
      } else {
        onMessagesChange(slot.base)
      }
    }
    setIsStreaming(false)
    setToolStatus(null)
    inFlightRef.current = null
  }, [onMessagesChange])

  const downloadResearchMd = useCallback((md: string) => {
    if (!md) return
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `urban-planning-report-${Date.now()}.md`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 150)
  }, [])

  const downloadResearchPdf = useCallback(async (md: string) => {
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
    let mapInserted = false
    const hasHeader = lines.some((l) => l.trimStart().startsWith('# '))

    const insertMap = () => {
      if (mapInserted || !onComposeMapFigure) return
      const figure = onComposeMapFigure(activeConversation?.title || 'Project Map')
      if (!figure) return
      try {
        const img = figure.toDataURL('image/png')
        const aspect = figure.height > 0 ? figure.width / figure.height : 1.6
        const drawW = maxLineWidth
        const drawH = drawW / aspect

        checkY(drawH + 34)
        doc.addImage(img, 'PNG', margin, y, drawW, drawH)
        y += drawH + 12

        // Compile dynamic caption showing active conversation title and visible layers
        const visibleLayers = (mapContext.layers || [])
          .filter((l) => l.visible)
          .map((l) => l.name)
        const conversationTitle = activeConversation?.title || 'Urban Project'
        const layersPart = visibleLayers.length > 0
          ? ` showing active layers: ${visibleLayers.join(', ')}`
          : ' with no active layers'
        const caption = `Figure 1: Composed Map for "${conversationTitle}"${layersPart}.`

        writeWrapped(caption, 9, 'italic', 12)
        y += 16
      } catch (err) {
        console.error('Failed to add map image to PDF:', err)
      }
      mapInserted = true
    }

    if (!hasHeader) {
      insertMap()
    }

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
        y += 12
        insertMap()
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
  }, [onComposeMapFigure, activeConversation, mapContext])

  useEffect(() => {
    setResearchPhase('idle')
    setResearchSteps([])
    setResearchMarkdown('')
    setResearchCitations([])
    setResearchExpanded(false)
    setResearchReasoning('')
    reportMdRef.current = ''
  }, [activeConversation?.id])

  /** Convert raw API error strings/objects into a short, friendly sentence. */
  const friendlyKeyError = (raw: string): string => {
    // OpenAI returns something like: "Error code: 401 - {'error': {'message': '...', 'code': 'invalid_api_key'}}"
    // Try to extract just the inner message.
    try {
      const jsonMatch = raw.match(/\{.*\}/s)
      if (jsonMatch) {
        // Replace single quotes with double quotes for JSON.parse
        const obj = JSON.parse(jsonMatch[0].replace(/'/g, '"'))
        const msg: string =
          obj?.error?.message ||
          obj?.message ||
          raw
        if (msg.includes('Incorrect API key')) return '❌ Incorrect API key — double-check your key at platform.openai.com/account/api-keys'
        if (msg.includes('exceeded') || msg.includes('quota')) return '⚠️ Quota exceeded — check your billing at platform.openai.com/account/billing'
        if (msg.includes('deactivated') || msg.includes('disabled')) return '🚫 This key has been deactivated by OpenAI'
        return `❌ ${msg.split('.')[0]}.`
      }
    } catch { /* fall through */ }
    if (raw.toLowerCase().includes('invalid')) return '❌ Invalid API key — please verify and try again'
    if (raw.toLowerCase().includes('quota') || raw.toLowerCase().includes('exceeded')) return '⚠️ Quota exceeded — check your billing'
    return raw
  }

  const validateAndSaveKey = async (keyToSave: string): Promise<boolean> => {
    setIsSavingKey(true)
    setKeyError(null)
    setKeySuccess(false)
    try {
      const res = await fetch('http://localhost:8765/api/chat/validate-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: keyToSave }),
      })
      const data = await res.json()
      if (data.valid) {
        const ok = await window.electronAPI.setAPIKey(keyToSave)
        if (ok) {
          setApiKey(keyToSave)
          setChatError(null)
          setIsSavingKey(false)
          setKeySuccess(true)
          setTimeout(() => {
            setKeySuccess(false)
            setShowApiKeyInput(false)
          }, 1800)
          return true
        } else {
          setKeyError('Failed to save key securely to system keychain.')
        }
      } else {
        setKeyError(friendlyKeyError(data.error || 'Invalid API Key. Please verify and try again.'))
      }
    } catch (err) {
      setKeyError('Could not reach verification server. Make sure the backend is running.')
    }
    setIsSavingKey(false)
    return false
  }

  const clearApiKey = async () => {
    const ok = await window.electronAPI.setAPIKey('')
    if (ok) {
      setApiKey('')
      setShowApiKeyInput(true)
      setChatError(null)
    }
  }

  const saveGoogleKey = async (keyToSave: string): Promise<boolean> => {
    setIsSavingGoogleKey(true)
    setGoogleKeyError(null)
    try {
      const ok = await window.electronAPI.setGoogleMapsKey(keyToSave)
      if (ok) {
        setGoogleKey(keyToSave)
        setIsSavingGoogleKey(false)
        setGoogleKeySuccess(true)
        setTimeout(() => setGoogleKeySuccess(false), 2000)
        return true
      } else {
        setGoogleKeyError('Failed to save key securely to system keychain.')
      }
    } catch (err) {
      setGoogleKeyError('Failed to save key.')
    }
    setIsSavingGoogleKey(false)
    return false
  }

  const clearGoogleKey = async () => {
    const ok = await window.electronAPI.setGoogleMapsKey('')
    if (ok) {
      setGoogleKey('')
    }
  }

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
        api_key: apiKey,
        google_maps_api_key: googleKey,
        image: documentImage
          ? {
              base64: documentImage.base64,
              mime_type: documentImage.mimeType,
              file_path: documentImage.filePath,
              file_name: documentImage.fileName,
            }
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

    if (!apiKey.trim()) {
      setShowApiKeyInput(true)
      setChatError({
        code: 'auth',
        message: 'An OpenAI API Key is required. Please configure your key in the settings panel above.',
      })
      return
    }

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
    <div ref={headerContainerRef} className="chat-panel">
      {/* ── Chat header ── */}
      <div className="chat-header">
        <span className="chat-header-title">
          {activeConversation?.title || 'Urban Planning Assistant'}
        </span>
        <div className="chat-header-actions">
          <button
            ref={historyBtnRef}
            className={`chat-header-action-btn ${showHistory ? 'active' : ''}`}
            onClick={() => {
              setShowHistory(!showHistory);
              setShowApiKeyInput(false);
            }}
            title="View chat history"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          </button>
          
          <button
            className="chat-header-action-btn"
            onClick={handleNewChat}
            title="Start a new chat"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── API Key Configuration Bar ── */}
      {isKeyLoaded && (
        <div className="api-key-config-bar">
          <div className="api-key-status-row">
            <div className="api-key-status-header">
              <div className="api-key-status-indicators">
                {apiKey ? (
                  <div className="api-key-status success">
                    <span className="api-key-indicator green">●</span>
                    <span className="api-key-label">OpenAI API Key active</span>
                  </div>
                ) : (
                  <div className="api-key-status warning">
                    <span className="api-key-indicator yellow">●</span>
                    <span className="api-key-label">OpenAI API Key required</span>
                  </div>
                )}

                {googleKey ? (
                  <div className="api-key-status success">
                    <span className="api-key-indicator green">●</span>
                    <span className="api-key-label">Google Maps Key active</span>
                  </div>
                ) : (
                  <div className="api-key-status info">
                    <span className="api-key-indicator gray">●</span>
                    <span className="api-key-label">Google Maps Key inactive (OSM fallback)</span>
                  </div>
                )}
              </div>

              {/* API Settings toggle — gear outline with API text inside */}
              <button
                className={`api-settings-btn ${showApiKeyInput ? 'active' : ''}`}
                onClick={() => {
                  setShowApiKeyInput(!showApiKeyInput);
                  setShowHistory(false);
                }}
                title="API Key Settings"
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" strokeLinecap="round" strokeLinejoin="round">
                  {/* Gear outline (outer boundary only, inner circle removed) */}
                  <path
                    d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"
                    stroke="currentColor"
                    strokeWidth="1.3"
                  />
                  {/* API text inside gear (larger font and re-centered) */}
                  <text
                    x="12.2"
                    y="14.2"
                    textAnchor="middle"
                    fontSize="6.2"
                    fontWeight="800"
                    fontFamily="Inter, system-ui, sans-serif"
                    fill="currentColor"
                    stroke="none"
                    letterSpacing="0.1"
                  >API</text>
                </svg>
              </button>
            </div>
          </div>

          {showApiKeyInput && (
            <div className="settings-drawer-container">
              {/* OpenAI Key Section */}
              <div className="setting-field-group">
                <label htmlFor="api-key-input-element" className="setting-field-label">OpenAI API Key (Required)</label>
                <div className="api-key-input-wrapper">
                  <input
                    key={apiKey}
                    type="password"
                    className="api-key-input-field"
                    defaultValue={apiKey}
                    id="api-key-input-element"
                    placeholder="sk-proj-..."
                    disabled={isSavingKey}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        const el = document.getElementById('api-key-input-element') as HTMLInputElement
                        if (el) validateAndSaveKey(el.value)
                      }
                    }}
                  />
                  <button
                    className={`api-key-save-btn ${keySuccess ? 'success' : ''}`}
                    onClick={() => {
                      const el = document.getElementById('api-key-input-element') as HTMLInputElement
                      if (el) validateAndSaveKey(el.value)
                    }}
                    disabled={isSavingKey}
                  >
                    {isSavingKey ? 'Saving...' : keySuccess ? 'Saved! ✓' : 'Save'}
                  </button>
                  {apiKey && (
                    <button
                      className="api-key-clear-btn"
                      onClick={clearApiKey}
                      disabled={isSavingKey}
                    >
                      Clear
                    </button>
                  )}
                </div>
                {keyError && (
                  <div className="api-key-error-msg">
                    <span className="api-key-error-icon">⚠</span>
                    <span>{keyError}</span>
                  </div>
                )}
              </div>

              {/* Google Maps Key Section */}
              <div className="setting-field-group">
                <label htmlFor="google-key-input-element" className="setting-field-label">Google Maps API Key (Optional)</label>
                <div className="api-key-input-wrapper">
                  <input
                    key={googleKey}
                    type="password"
                    className="api-key-input-field"
                    defaultValue={googleKey}
                    id="google-key-input-element"
                    placeholder="AIzaSy..."
                    disabled={isSavingGoogleKey}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        const el = document.getElementById('google-key-input-element') as HTMLInputElement
                        if (el) saveGoogleKey(el.value)
                      }
                    }}
                  />
                  <button
                    className={`api-key-save-btn ${googleKeySuccess ? 'success' : ''}`}
                    onClick={() => {
                      const el = document.getElementById('google-key-input-element') as HTMLInputElement
                      if (el) saveGoogleKey(el.value)
                    }}
                    disabled={isSavingGoogleKey}
                  >
                    {isSavingGoogleKey ? 'Saving...' : googleKeySuccess ? 'Saved! ✓' : 'Save'}
                  </button>
                  {googleKey && (
                    <button
                      className="api-key-clear-btn"
                      onClick={clearGoogleKey}
                      disabled={isSavingGoogleKey}
                    >
                      Clear
                    </button>
                  )}
                </div>
                {googleKeyError && (
                  <div className="api-key-error-msg">
                    <span className="api-key-error-icon">⚠</span>
                    <span>{googleKeyError}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Conversation history dropdown ── */}
      {showHistory && (
        <div ref={historyListRef} className="chat-history-list">
          {conversations.length === 0 ? (
            <div className="chat-history-empty">No conversations yet</div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={`chat-history-item ${conv.id === activeConversation?.id ? 'active' : ''}`}
                onClick={() => {
                  if (editingConversationId === conv.id) return
                  onSelectConversation(conv.id)
                  setShowHistory(false)
                  wsRef.current?.close()
                  wsRef.current = null
                }}
              >
                <div className="chat-history-item-content">
                  {editingConversationId === conv.id ? (
                    <input
                      type="text"
                      className="chat-history-rename-input"
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          onRenameConversation?.(conv.id, editingTitle.trim() || 'New chat')
                          setEditingConversationId(null)
                        } else if (e.key === 'Escape') {
                          setEditingConversationId(null)
                        }
                      }}
                      onBlur={() => {
                        onRenameConversation?.(conv.id, editingTitle.trim() || 'New chat')
                        setEditingConversationId(null)
                      }}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <span className="chat-history-item-title">{conv.title}</span>
                  )}
                  <span className="chat-history-item-meta">
                    {conv.messages.length} msg{conv.messages.length !== 1 ? 's' : ''} &middot;{' '}
                    {formatTime(conv.createdAt)}
                  </span>
                </div>
                {editingConversationId !== conv.id && (
                  <button
                    className="chat-history-rename-btn"
                    onClick={(e) => {
                      e.stopPropagation()
                      setEditingConversationId(conv.id)
                      setEditingTitle(conv.title)
                    }}
                    title="Rename conversation"
                  >
                    ✎
                  </button>
                )}
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
          <div className="chat-error-content-wrapper">
            <span className="chat-error-code">{chatError.code}</span>
            <span className="chat-error-msg">{chatError.message}</span>
            {(chatError.code === 'auth' || chatError.code === 'rate_limit') && (
              <div className="chat-error-inline-form">
                <input
                  type="password"
                  className="chat-error-inline-input"
                  id="chat-error-inline-input-element"
                  placeholder="Enter new API key (sk-proj-...)"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      const el = document.getElementById('chat-error-inline-input-element') as HTMLInputElement
                      if (el) validateAndSaveKey(el.value)
                    }
                  }}
                />
                <button
                  className="chat-error-inline-save-btn"
                  onClick={() => {
                    const el = document.getElementById('chat-error-inline-input-element') as HTMLInputElement
                    if (el) validateAndSaveKey(el.value)
                  }}
                >
                  Save
                </button>
              </div>
            )}
          </div>
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
            <img src={appIcon} className="chat-empty-logo" alt="App Logo" />
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
          // Don't render placeholder/empty assistant turns unless they contain inline research metadata
          if (msg.role === 'assistant' && !msg.content.trim() && !msg.research) return null
          return (
            <div key={i} className={`chat-msg ${msg.role}`}>
              <div className="chat-msg-role">{msg.role === 'user' ? 'You' : 'Assistant'}</div>
              <div className="chat-msg-body">
                {msg.research ? (
                  <ResearchBubble
                    phase={msg.research.phase}
                    steps={msg.research.steps}
                    reasoning={msg.research.reasoning}
                    markdown={msg.research.markdown}
                    citations={msg.research.citations}
                    expanded={researchExpanded}
                    onToggleExpand={() => setResearchExpanded((v) => !v)}
                    onDownloadMd={() => downloadResearchMd(msg.research?.markdown || '')}
                    onDownloadPdf={() => downloadResearchPdf(msg.research?.markdown || '')}
                  />
                ) : msg.role === 'assistant' ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeHighlight]}
                    components={{
                      pre: CodePre,
                      ...headingComponents
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
        {/* Tool status + streaming dots are hidden while a research run is active on the screen */}
        {toolStatus && messages[messages.length - 1]?.research?.phase !== 'running' && (
          <div className="chat-tool-status">
            <span className="tool-dot" />
            {toolStatus}
          </div>
        )}
        {isStreaming && !toolStatus && messages[messages.length - 1]?.research?.phase !== 'running' && (
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
              !apiKey.trim()
                ? 'Please configure your OpenAI API Key above to start...'
                : activeConversation
                ? 'Ask anything about your project...'
                : 'Start a new conversation...'
            }
            disabled={!apiKey.trim()}
            rows={1}
          />
          {isStreaming ? (
            <button
              className="chat-stop-btn"
              onClick={handleStopStreaming}
              title="Stop generating"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="4" y="4" width="8" height="8" rx="1" fill="currentColor" />
              </svg>
            </button>
          ) : (
            <button
              className="chat-send-btn"
              onClick={sendMessage}
              disabled={!input.trim()}
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
          )}
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
