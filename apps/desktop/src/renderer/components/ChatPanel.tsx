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
        {messages.map((msg, i) => (
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
        ))}
        {toolStatus && (
          <div className="chat-tool-status">
            <span className="tool-dot" />
            {toolStatus}
          </div>
        )}
        {isStreaming && !toolStatus && (
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
