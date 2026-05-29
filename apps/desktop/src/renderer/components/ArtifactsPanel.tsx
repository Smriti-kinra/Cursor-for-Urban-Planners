import { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { Artifact, ChatMessage, MapContext } from '../types'
import './ArtifactsPanel.css'

const API_BASE = 'http://localhost:8765/api/artifacts'

/** Preview-only artifact returned by GET /api/artifacts (truncated content) */
interface ArtifactPreview extends Omit<Artifact, 'content'> {
  preview: string
}

interface ArtifactsPanelProps {
  revision?: number
  onAddToMap: (geojson: object, name: string) => void
  chatHistory?: ChatMessage[]
  mapContext?: MapContext
}

export default function ArtifactsPanel({ revision, onAddToMap, chatHistory = [], mapContext }: ArtifactsPanelProps) {
  const [artifacts, setArtifacts] = useState<ArtifactPreview[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [fullArtifact, setFullArtifact] = useState<Artifact | null>(null)
  const [loadingFull, setLoadingFull] = useState(false)

  // Create-form state
  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [artifactType, setArtifactType] = useState('note')
  const [format, setFormat] = useState<'markdown' | 'table' | 'geojson'>('markdown')

  // Edit state
  const [editingTitle, setEditingTitle] = useState<number | null>(null)
  const [editTitleValue, setEditTitleValue] = useState('')
  const [editingContent, setEditingContent] = useState(false)
  const [editContentValue, setEditContentValue] = useState('')

  // Report generation state
  type ReportPhase = 'idle' | 'running' | 'done' | 'error'
  const [reportPhase, setReportPhase] = useState<ReportPhase>('idle')
  const [reportSteps, setReportSteps] = useState<string[]>([])
  const [reportMarkdown, setReportMarkdown] = useState('')
  const [reportError, setReportError] = useState('')
  const reportAbortRef = useRef<AbortController | null>(null)

  const fetchArtifacts = useCallback(async () => {
    try {
      const res = await fetch(API_BASE)
      if (res.ok) {
        const data = await res.json()
        setArtifacts(data)
      }
    } catch {
      /* backend may not be available */
    }
  }, [])

  const generateReport = useCallback(async () => {
    setReportPhase('running')
    setReportSteps([])
    setReportMarkdown('')
    setReportError('')

    const controller = new AbortController()
    reportAbortRef.current = controller

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
              } else if (currentEvent === 'done') {
                setReportPhase((prev) => (prev !== 'done' ? 'done' : prev))
              }
            } catch { /* malformed SSE line */ }
            currentEvent = ''
          }
        }
      }
      // Guard against stream closing without a terminal event
      setReportPhase((prev) => (prev === 'running' ? 'error' : prev))
      setReportError((prev) => prev || 'Stream ended unexpectedly.')
    } catch (err: unknown) {
      if ((err as { name?: string }).name !== 'AbortError') {
        setReportError(String(err))
        setReportPhase('error')
      }
    }
  }, [chatHistory, mapContext])

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
    setTimeout(() => URL.revokeObjectURL(url), 150)
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

  useEffect(() => {
    fetchArtifacts()
  }, [fetchArtifacts])

  useEffect(() => {
    if (revision !== undefined && revision > 0) fetchArtifacts()
  }, [revision, fetchArtifacts])

  // Fetch full artifact when selection changes
  useEffect(() => {
    if (selectedId === null) {
      setFullArtifact(null)
      setEditingContent(false)
      return
    }
    const controller = new AbortController()
    setLoadingFull(true)
    fetch(`${API_BASE}/${selectedId}`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Artifact | null) => {
        if (data) setFullArtifact(data)
        setLoadingFull(false)
        setEditingContent(false)
      })
      .catch(() => setLoadingFull(false))
    return () => controller.abort()
  }, [selectedId])

  const createArtifact = async (): Promise<void> => {
    if (!title.trim()) return
    try {
      const res = await fetch(API_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, artifact_type: artifactType, format }),
      })
      if (res.ok) {
        setTitle('')
        setContent('')
        setShowForm(false)
        fetchArtifacts()
      }
    } catch {
      /* backend may not be available */
    }
  }

  const deleteArtifact = async (id: number): Promise<void> => {
    try {
      await fetch(`${API_BASE}/${id}`, { method: 'DELETE' })
      if (selectedId === id) setSelectedId(null)
      fetchArtifacts()
    } catch {
      /* backend may not be available */
    }
  }

  const saveTitle = async (id: number, newTitle: string): Promise<void> => {
    if (!newTitle.trim()) return
    try {
      await fetch(`${API_BASE}/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle }),
      })
      setEditingTitle(null)
      fetchArtifacts()
      if (fullArtifact && fullArtifact.id === id) {
        setFullArtifact((prev) => (prev ? { ...prev, title: newTitle } : null))
      }
    } catch {
      /* backend may not be available */
    }
  }

  const saveContent = async (): Promise<void> => {
    if (!fullArtifact) return
    try {
      await fetch(`${API_BASE}/${fullArtifact.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContentValue }),
      })
      setEditingContent(false)
      setFullArtifact((prev) => (prev ? { ...prev, content: editContentValue } : null))
      fetchArtifacts()
    } catch {
      /* backend may not be available */
    }
  }

  const handleToggleSelect = (id: number): void => {
    setSelectedId((prev) => (prev === id ? null : id))
  }

  // ── Format-aware detail renderer ──

  const renderDetail = (artifact: Artifact): React.ReactNode => {
    const { id, title: aTitle, format: fmt, content, meta } = artifact

    if (fmt === 'markdown') {
      return (
        <div className="artifact-detail">
          {editingContent ? (
            <>
              <textarea
                className="artifact-edit-area"
                value={editContentValue}
                onChange={(e) => setEditContentValue(e.target.value)}
              />
              <div className="artifact-actions">
                <button className="save-btn" onClick={saveContent}>Save</button>
                <button className="cancel-btn" onClick={() => setEditingContent(false)}>Cancel</button>
              </div>
            </>
          ) : (
            <>
              <div className="artifact-detail-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {content}
                </ReactMarkdown>
              </div>
              <div className="artifact-actions">
                <button
                  className="edit-btn"
                  onClick={() => { setEditContentValue(content); setEditingContent(true) }}
                >
                  Edit
                </button>
                <a
                  className="download-btn"
                  href={`${API_BASE}/${id}/download`}
                  download
                >
                  Download
                </a>
              </div>
            </>
          )}
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }

    if (fmt === 'table') {
      let tableData: { columns: string[]; rows: unknown[][] } | null = null
      try {
        tableData = JSON.parse(content)
      } catch {
        /* malformed content */
      }

      return (
        <div className="artifact-detail">
          {editingContent ? (
            <>
              <textarea
                className="artifact-edit-area"
                value={editContentValue}
                onChange={(e) => setEditContentValue(e.target.value)}
              />
              <div className="artifact-actions">
                <button className="save-btn" onClick={saveContent}>Save</button>
                <button className="cancel-btn" onClick={() => setEditingContent(false)}>Cancel</button>
              </div>
            </>
          ) : (
            <>
              {tableData ? (
                <div className="artifact-table-wrapper">
                  <table className="artifact-table">
                    <thead>
                      <tr>
                        {tableData.columns.map((col, i) => (
                          <th key={i}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {tableData.rows.map((row, ri) => (
                        <tr key={ri}>
                          {row.map((cell, ci) => (
                            <td key={ci}>{String(cell ?? '')}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="artifact-geojson-summary">Invalid table data</p>
              )}
              <div className="artifact-actions">
                <button
                  className="edit-btn"
                  onClick={() => { setEditContentValue(content); setEditingContent(true) }}
                >
                  Edit
                </button>
                <a
                  className="download-btn"
                  href={`${API_BASE}/${id}/download`}
                  download
                >
                  Download
                </a>
              </div>
            </>
          )}
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }

    if (fmt === 'image') {
      const downloadUrl = `${API_BASE}/${id}/download`
      return (
        <div className="artifact-detail">
          <img
            className="artifact-image-thumb"
            src={downloadUrl}
            alt={aTitle}
            onClick={() => window.open(downloadUrl, '_blank')}
          />
          <div className="artifact-actions">
            <a className="download-btn" href={downloadUrl} download>Download</a>
          </div>
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }

    if (fmt === 'geojson') {
      let featureCount: number | null = null
      let bbox: string | null = null
      if (meta) {
        try {
          const parsed = JSON.parse(meta)
          featureCount = parsed.feature_count ?? null
          bbox = parsed.bbox ? JSON.stringify(parsed.bbox) : null
        } catch {
          /* ignore */
        }
      }
      return (
        <div className="artifact-detail">
          <p className="artifact-geojson-summary">
            {featureCount !== null ? `${featureCount} feature(s)` : 'GeoJSON'}
            {bbox ? ` · bbox: ${bbox}` : ''}
          </p>
          <div className="artifact-actions">
            <button
              className="add-to-map-btn"
              onClick={() => {
                try {
                  const geojson = JSON.parse(fullArtifact!.content)
                  onAddToMap(geojson, fullArtifact!.title)
                } catch {
                  console.error('Invalid GeoJSON content')
                }
              }}
            >
              Add to map
            </button>
            <a className="download-btn" href={`${API_BASE}/${id}/download`} download>
              Download
            </a>
          </div>
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }

    // Fallback for unknown formats
    return (
      <div className="artifact-detail">
        <p>{content}</p>
        <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
      </div>
    )
  }

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
        <button className="new-artifact-btn" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ New'}
        </button>
        <button className="refresh-btn" onClick={fetchArtifacts}>
          &#8635;
        </button>
      </div>

      {showForm && (
        <div className="artifact-form">
          <input
            className="artifact-input"
            placeholder="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <select
            className="artifact-select"
            value={artifactType}
            onChange={(e) => setArtifactType(e.target.value)}
          >
            <option value="note">Note</option>
            <option value="analysis">Analysis</option>
            <option value="report">Report</option>
            <option value="sketch">Sketch</option>
          </select>
          <select
            className="artifact-select"
            value={format}
            onChange={(e) => setFormat(e.target.value as 'markdown' | 'table' | 'geojson')}
          >
            <option value="markdown">Markdown</option>
            <option value="table">Table</option>
            <option value="geojson">GeoJSON</option>
          </select>
          <textarea
            className="artifact-textarea"
            placeholder="Content..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
          />
          <button className="save-btn" onClick={createArtifact}>
            Save
          </button>
        </div>
      )}

      <div className="artifacts-list">
        {artifacts.length === 0 && !showForm && (
          <div className="artifacts-empty">
            <p>No artifacts yet</p>
            <p className="hint">Save notes, analyses, and reports here.</p>
          </div>
        )}
        {artifacts.map((a) => (
          <div
            key={a.id}
            className={`artifact-item ${selectedId === a.id ? 'selected' : ''}`}
            onClick={() => handleToggleSelect(a.id)}
          >
            <div className="artifact-item-header">
              <span className="artifact-type-badge">{a.format ?? a.artifact_type}</span>
              {editingTitle === a.id ? (
                <input
                  className="artifact-title-input"
                  value={editTitleValue}
                  autoFocus
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setEditTitleValue(e.target.value)}
                  onBlur={() => saveTitle(a.id, editTitleValue)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') saveTitle(a.id, editTitleValue)
                    if (e.key === 'Escape') setEditingTitle(null)
                  }}
                />
              ) : (
                <span className="artifact-title">{a.title}</span>
              )}
              <button
                className="edit-title-btn"
                title="Edit title"
                onClick={(e) => {
                  e.stopPropagation()
                  setEditingTitle(a.id)
                  setEditTitleValue(a.title)
                }}
              >
                ✎
              </button>
              <button
                className="delete-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  deleteArtifact(a.id)
                }}
              >
                &times;
              </button>
            </div>
            {selectedId === a.id && (
              loadingFull ? (
                <div className="artifact-detail">
                  <p className="artifact-geojson-summary">Loading…</p>
                </div>
              ) : fullArtifact && fullArtifact.id === a.id ? (
                renderDetail(fullArtifact)
              ) : null
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
