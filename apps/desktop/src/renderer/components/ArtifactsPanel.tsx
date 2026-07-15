import { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { Artifact } from '../types'
import './ArtifactsPanel.css'

const API_BASE = 'http://localhost:8765/api/artifacts'

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

/** Preview-only artifact returned by GET /api/artifacts (truncated content) */
interface ArtifactPreview extends Omit<Artifact, 'content'> {
  preview: string
}

interface ArtifactsPanelProps {
  revision?: number
  onAddToMap: (geojson: object, name: string) => void
  showSidebar?: boolean
  sidebarWidth?: number
  onLeftResizeStart?: (e: React.MouseEvent) => void
}

export default function ArtifactsPanel({
  revision,
  onAddToMap,
  showSidebar = true,
  sidebarWidth = 260,
  onLeftResizeStart,
}: ArtifactsPanelProps) {
  const [artifacts, setArtifacts] = useState<ArtifactPreview[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [fullArtifact, setFullArtifact] = useState<Artifact | null>(null)
  const [loadingFull, setLoadingFull] = useState(false)

  const containerRef = useRef<HTMLDivElement>(null)
  const [isWide, setIsWide] = useState(false)

  const [draggedArtId, setDraggedArtId] = useState<number | null>(null)
  const [dragOverArtId, setDragOverArtId] = useState<number | null>(null)
  const [dropArtPosition, setDropArtPosition] = useState<'before' | 'after' | null>(null)

  const handleArtDragStart = (id: number, e: React.DragEvent) => {
    setDraggedArtId(id)
    e.dataTransfer.setData('text/plain', String(id))
  }

  const handleArtDragOver = (id: number, e: React.DragEvent) => {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const relativeY = e.clientY - rect.top
    const pos = relativeY < rect.height / 2 ? 'before' : 'after'
    setDragOverArtId(id)
    setDropArtPosition(pos)
  }

  const handleArtDragEnd = () => {
    setDraggedArtId(null)
    setDragOverArtId(null)
    setDropArtPosition(null)
  }

  const handleArtDrop = (targetId: number, e: React.DragEvent) => {
    e.preventDefault()
    if (draggedArtId === null || draggedArtId === targetId) return

    const draggedArt = artifacts.find((a) => a.id === draggedArtId)
    if (!draggedArt) return

    const remainingArts = artifacts.filter((a) => a.id !== draggedArtId)
    let insertIndex = remainingArts.findIndex((a) => a.id === targetId)
    if (insertIndex !== -1) {
      if (dropArtPosition === 'after') {
        insertIndex += 1
      }
      const newArts = [
        ...remainingArts.slice(0, insertIndex),
        draggedArt,
        ...remainingArts.slice(insertIndex),
      ]
      setArtifacts(newArts)
      localStorage.setItem('artifacts_order', JSON.stringify(newArts.map((a) => a.id)))
    }
    handleArtDragEnd()
  }

  useEffect(() => {
    if (!containerRef.current) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setIsWide(entry.contentRect.width >= 580)
      }
    })
    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

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

  const fetchArtifacts = useCallback(async () => {
    try {
      const res = await fetch(API_BASE)
      if (res.ok) {
        const data = await res.json()
        const savedOrder = localStorage.getItem('artifacts_order')
        if (savedOrder) {
          const orderIds: number[] = JSON.parse(savedOrder)
          const sorted = [...data].sort((a, b) => {
            const idxA = orderIds.indexOf(a.id)
            const idxB = orderIds.indexOf(b.id)
            if (idxA === -1 && idxB === -1) return 0
            if (idxA === -1) return 1
            if (idxB === -1) return -1
            return idxA - idxB
          })
          setArtifacts(sorted)
        } else {
          setArtifacts(data)
        }
      }
    } catch {
      /* backend may not be available */
    }
  }, [])

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
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeHighlight]}
                  components={headingComponents}
                >
                  {content}
                </ReactMarkdown>
              </div>
              <div className="artifact-actions">
                <button
                  className="edit-btn"
                  onClick={() => { setEditContentValue(content); setEditingContent(true) }}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <path d="M12 20h9"></path>
                    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                  </svg>
                  Edit
                </button>
                <a
                  className="download-btn docx-btn"
                  href={`${API_BASE}/${id}/docx`}
                  download
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <line x1="16" y1="13" x2="8" y2="13"></line>
                    <line x1="16" y1="17" x2="8" y2="17"></line>
                    <polyline points="10 9 9 9 8 9"></polyline>
                  </svg>
                  Word
                </a>
                <a
                  className="download-btn pdf-btn"
                  href={`${API_BASE}/${id}/pdf`}
                  download
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                  PDF
                </a>
                <a
                  className="download-btn latex-btn"
                  href={`${API_BASE}/${id}/latex`}
                  download
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <polyline points="16 18 22 12 16 6"></polyline>
                    <polyline points="8 6 2 12 8 18"></polyline>
                  </svg>
                  LaTeX
                </a>
                <a
                  className="download-btn markdown-btn"
                  href={`${API_BASE}/${id}/download`}
                  download
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                  </svg>
                  Markdown
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

  const shouldShowSidebar = showSidebar || !isWide

  return (
    <div ref={containerRef} className={`artifacts-panel ${isWide ? 'wide' : ''}`}>
      {shouldShowSidebar && (
        <div className="artifacts-sidebar" style={isWide ? { width: sidebarWidth, flex: `0 0 ${sidebarWidth}px` } : undefined}>
          <div className="artifacts-toolbar">
            <button className="new-artifact-btn" onClick={() => setShowForm(!showForm)}>
              {showForm ? 'Cancel' : '+ New Artifact'}
            </button>
            <button className="refresh-btn" onClick={fetchArtifacts} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M23 4v6h-6"></path>
                <path d="M1 20v-6h6"></path>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
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
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ opacity: 0.35, marginBottom: 4 }}>
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                </svg>
                <p className="title">No artifacts yet</p>
                <p className="hint">Save notes, analyses, and reports here.</p>
              </div>
            )}
            {artifacts.map((a) => (
              <div
                key={a.id}
                className={`artifact-item ${selectedId === a.id ? 'selected' : ''} ${dragOverArtId === a.id ? `drag-over-${dropArtPosition}` : ''}`}
                onClick={() => handleToggleSelect(a.id)}
                draggable={true}
                onDragStart={(e) => handleArtDragStart(a.id, e)}
                onDragOver={(e) => handleArtDragOver(a.id, e)}
                onDrop={(e) => handleArtDrop(a.id, e)}
                onDragEnd={handleArtDragEnd}
                style={{ cursor: 'grab' }}
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
                    className="rename-btn"
                    onClick={(e) => {
                      e.stopPropagation()
                      setEditingTitle(a.id)
                      setEditTitleValue(a.title)
                    }}
                    style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M12 20h9"></path>
                      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                    </svg>
                  </button>
                  <button
                    className="delete-btn"
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteArtifact(a.id)
                    }}
                    style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                  </button>
                </div>
                {!isWide && selectedId === a.id && (
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
      )}

      {shouldShowSidebar && isWide && onLeftResizeStart && (
        <div className="resize-handle" onMouseDown={onLeftResizeStart} />
      )}

      {isWide && (
        <div className="artifacts-detail-pane">
          {selectedId === null ? (
            <div className="artifacts-empty-detail">
              <div className="artifacts-empty-detail-icon">
                <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" style={{ opacity: 0.35 }}>
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                  <line x1="16" y1="13" x2="8" y2="13"></line>
                  <line x1="16" y1="17" x2="8" y2="17"></line>
                  <polyline points="10 9 9 9 8 9"></polyline>
                </svg>
              </div>
              <p className="artifacts-empty-detail-title">Select an artifact to view its contents</p>
              <p className="artifacts-empty-detail-hint">View reports, maps, analyses, and tables in full page width.</p>
            </div>
          ) : loadingFull ? (
            <div className="artifacts-detail-loading" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="spinning" style={{ marginRight: 6 }}>
                <path d="M23 4v6h-6"></path>
                <path d="M1 20v-6h6"></path>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
              Loading artifact contents...
            </div>
          ) : fullArtifact && fullArtifact.id === selectedId ? (
            <div className="artifacts-detail-content">
              <div className="artifacts-detail-header">
                <h2 className="artifacts-detail-title">{fullArtifact.title}</h2>
                <span className="artifacts-detail-badge">{fullArtifact.format ?? fullArtifact.artifact_type}</span>
              </div>
              {renderDetail(fullArtifact)}
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
