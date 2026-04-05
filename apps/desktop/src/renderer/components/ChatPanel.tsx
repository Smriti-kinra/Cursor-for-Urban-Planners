import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'
import { ChatMessage, Conversation, MapContext, MapAction } from '../types'
import './ChatPanel.css'

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
}: ChatPanelProps) {
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [toolStatus, setToolStatus] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([])
  const [currentModel, setCurrentModel] = useState<string>('')
  const [isSwitchingModel, setIsSwitchingModel] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pendingInputRef = useRef<string | null>(null)

  const messages = activeConversation?.messages ?? []

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

  const connectWebSocket = (): Promise<WebSocket> => {
    return new Promise((resolve, reject) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        resolve(wsRef.current)
        return
      }
      const ws = new WebSocket(BACKEND_WS)
      ws.onopen = () => {
        wsRef.current = ws
        resolve(ws)
      }
      ws.onerror = () => reject(new Error('WebSocket connection failed'))
      ws.onclose = () => {
        wsRef.current = null
      }
    })
  }

  const sendMessageDirect = async (text: string): Promise<void> => {
    if (!text.trim() || isStreaming || !activeConversation) return

    const userMessage: ChatMessage = { role: 'user', content: text.trim(), timestamp: Date.now() }
    const updated = [...messages, userMessage]
    onMessagesChange(updated)
    setIsStreaming(true)
    setToolStatus(null)

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }

    try {
      const ws = await connectWebSocket()
      let assistantContent = ''
      onMessagesChange([...updated, { role: 'assistant', content: '', timestamp: Date.now() }])

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'stream') {
          assistantContent += data.content
          onMessagesChange([
            ...updated,
            { role: 'assistant', content: assistantContent, timestamp: Date.now() },
          ])
        } else if (data.type === 'tool_use') {
          setToolStatus(`Using ${data.tool}...`)
        } else if (data.type === 'action') {
          onMapAction({ type: data.action, payload: data.payload })
        } else if (data.type === 'end') {
          setIsStreaming(false)
          setToolStatus(null)
        }
      }

      ws.send(
        JSON.stringify({
          content: userMessage.content,
          map_context: mapContext,
        }),
      )
    } catch {
      onMessagesChange([
        ...updated,
        {
          role: 'assistant',
          content: 'Failed to connect to backend. Make sure the server is running.',
          timestamp: Date.now(),
        },
      ])
      setIsStreaming(false)
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
    onCreateConversation()
    setShowHistory(false)
  }

  const handleModelChange = async (modelId: string) => {
    if (modelId === currentModel || isSwitchingModel) return
    setIsSwitchingModel(true)
    try {
      const result = await window.electronAPI.switchModel(modelId)
      setCurrentModel(modelId)
      // Close the WS so the next message gets a fresh opencode session with the new model
      wsRef.current?.close()
      wsRef.current = null
      if (result.requiresManualRestart) {
        setToolStatus('Model updated — restart opencode to apply')
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
              <span className="suggestion" onClick={() => setInput('Analyze this zoning layout')}>
                Analyze this zoning layout
              </span>
              <span
                className="suggestion"
                onClick={() => setInput("What's the total area of my polygons?")}
              >
                What&apos;s the total area of my polygons?
              </span>
              <span
                className="suggestion"
                onClick={() => setInput('Search for transit regulations')}
              >
                Search for transit regulations
              </span>
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
                <option key={m.id} value={m.id}>
                  {m.local ? '◆ ' : '☁ '}{m.name}
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
