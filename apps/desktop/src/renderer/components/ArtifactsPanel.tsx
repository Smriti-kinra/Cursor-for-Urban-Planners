import { useState, useEffect, useCallback } from 'react'
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
}

export default function ArtifactsPanel({ revision, onAddToMap }: ArtifactsPanelProps) {
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

  const handleExportPDF = async (artifact: Artifact): Promise<void> => {
    const element = document.querySelector('.artifact-detail-markdown')
    if (!element) return

    const printStyles = `
      <style>
        body {
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          color: #334155;
          line-height: 1.7;
          padding: 40px;
          max-width: 800px;
          margin: 0 auto;
        }
        h1 {
          font-family: 'Outfit', sans-serif;
          font-size: 30px;
          border-bottom: 2px solid #cbd5e1;
          padding-bottom: 10px;
          color: #0f172a;
          margin-top: 0;
          margin-bottom: 24px;
        }
        h2 {
          font-family: 'Outfit', sans-serif;
          font-size: 20px;
          color: #1e293b;
          margin-top: 36px;
          margin-bottom: 12px;
          border-bottom: 1.5px solid #e2e8f0;
          padding-bottom: 6px;
          page-break-before: always;
          break-before: page;
        }
        /* Don't page break on first H2 or right after Title */
        h1 + h2,
        h2:first-of-type {
          page-break-before: avoid !important;
          break-before: avoid !important;
        }
        h3 {
          font-family: 'Outfit', sans-serif;
          font-size: 16px;
          color: #334155;
          margin-top: 24px;
          margin-bottom: 8px;
        }
        p, li {
          font-size: 14px;
          color: #334155;
        }
        p {
          margin-bottom: 16px;
        }
        /* Table of Contents Formatting and Page Breaking */
        ul:has(li > a[href^="#"]) {
          background: #f8fafc;
          border: 1px solid #cbd5e1;
          border-radius: 8px;
          padding: 24px;
          margin: 20px 0 40px;
          list-style-type: none;
          page-break-after: always;
          break-after: page;
        }
        ul:has(li > a[href^="#"]) li {
          margin-bottom: 8px;
          font-size: 14px;
        }
        ul:has(li > a[href^="#"]) a {
          color: #2563eb !important;
          text-decoration: none !important;
          font-weight: 500;
        }
        ul:has(li > a[href^="#"]) a:hover {
          text-decoration: underline !important;
        }
        ul:not(:has(a[href^="#"])), ol {
          padding-left: 20px;
          margin-bottom: 16px;
        }
        li {
          margin-bottom: 6px;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          margin: 24px 0;
          font-size: 13px;
        }
        th, td {
          border: 1px solid #cbd5e1;
          padding: 8px 12px;
          text-align: left;
        }
        th {
          background-color: #f8fafc;
          font-weight: 600;
          color: #0f172a;
          border-bottom: 2px solid #cbd5e1;
        }
        tr:nth-child(even) {
          background-color: #f8fafc;
        }
        code {
          font-family: 'Courier New', monospace;
          background-color: #f1f5f9;
          padding: 2px 4px;
          border-radius: 4px;
          font-size: 13px;
        }
        pre {
          background-color: #f8fafc;
          border: 1px solid #e2e8f0;
          padding: 12px;
          border-radius: 6px;
          overflow-x: auto;
          margin-bottom: 16px;
        }
        pre code {
          background-color: transparent;
          padding: 0;
        }
        blockquote {
          border-left: 4px solid #cbd5e1;
          background-color: #f8fafc;
          padding: 12px 16px;
          margin: 16px 0;
          color: #64748b;
          font-style: italic;
          border-radius: 0 6px 6px 0;
        }
        a {
          color: #2563eb !important;
          text-decoration: underline !important;
        }
        @media print {
          body {
            padding: 0;
          }
          h1, h2, h3, h4, h5, h6 {
            page-break-after: avoid;
            break-after: avoid;
          }
          tr, img, figure, blockquote {
            page-break-inside: avoid;
            break-inside: avoid;
          }
          a[href]::after {
            content: "" !important;
          }
        }
      </style>
    `
    const titleSafe = (artifact.title || 'artifact').replace(/\s+/g, '_').replace(/[\/\\?%*:|"<>\.]/g, '-')
    const htmlPayload = `
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8">
          <title>${artifact.title}</title>
          <link rel="preconnect" href="https://fonts.googleapis.com">
          <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
          <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
          ${printStyles}
        </head>
        <body>
          ${element.innerHTML}
        </body>
      </html>
    `
    await window.electronAPI.savePDF(htmlPayload, `${titleSafe}_Report.pdf`)
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
                >
                  ✏️ Edit
                </button>
                <a
                  className="download-btn docx-btn"
                  href={`${API_BASE}/${id}/docx`}
                  download
                >
                  📄 Word
                </a>
                <button
                  className="download-btn pdf-btn"
                  onClick={() => handleExportPDF(artifact)}
                >
                  🖨️ PDF
                </button>
                <a
                  className="download-btn latex-btn"
                  href={`${API_BASE}/${id}/latex`}
                  download
                >
                  𝛌 LaTeX
                </a>
                <a
                  className="download-btn markdown-btn"
                  href={`${API_BASE}/${id}/download`}
                  download
                >
                  ⬇️ Markdown
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
