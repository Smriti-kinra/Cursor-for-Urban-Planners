import { useState, useRef, useEffect } from 'react'
import './ChatPanel.css'

const BACKEND_WS = 'ws://localhost:8765/api/chat/ws'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = (): void => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(scrollToBottom, [messages])

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

  const sendMessage = async (): Promise<void> => {
    if (!input.trim() || isStreaming) return

    const userMessage: Message = { role: 'user', content: input.trim() }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsStreaming(true)

    try {
      const ws = await connectWebSocket()
      let assistantContent = ''
      setMessages((prev) => [...prev, { role: 'assistant', content: '' }])

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'stream') {
          assistantContent += data.content
          setMessages((prev) => {
            const updated = [...prev]
            updated[updated.length - 1] = {
              role: 'assistant',
              content: assistantContent
            }
            return updated
          })
        } else if (data.type === 'end') {
          setIsStreaming(false)
        }
      }

      ws.send(JSON.stringify({ content: userMessage.content }))
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Failed to connect to backend. Make sure the server is running.'
        }
      ])
      setIsStreaming(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="chat-panel">
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p className="chat-empty-title">Urban Planning Assistant</p>
            <p className="chat-hint">
              Ask about zoning, land use, transportation, or any planning topic.
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <div className="message-role">{msg.role === 'user' ? 'You' : 'Assistant'}</div>
            <div className="message-content">{msg.content}</div>
          </div>
        ))}
        {isStreaming && <div className="streaming-indicator">...</div>}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask your planning assistant..."
          rows={3}
        />
        <button className="send-btn" onClick={sendMessage} disabled={!input.trim() || isStreaming}>
          Send
        </button>
      </div>
    </div>
  )
}
