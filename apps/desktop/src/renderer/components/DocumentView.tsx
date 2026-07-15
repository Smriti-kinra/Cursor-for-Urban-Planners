import { useState } from 'react'
import './DocumentView.css'
import { IMAGE_EXTS, MIME_MAP, rasterizePdfPage } from '../lib/pdf-raster'

export interface DocumentImage {
  base64: string
  mimeType: string
  fileName: string
  filePath?: string
  /** For multi-page sources, the page number that was rasterized (1-indexed). */
  page?: number
  /** For multi-page sources, the total number of pages. */
  totalPages?: number
}

interface DocumentViewProps {
  onImageChange: (img: DocumentImage | null) => void
  showSidebar?: boolean
  sidebarWidth?: number
  onLeftResizeStart?: (e: React.MouseEvent) => void
}

interface OpenDocument {
  id: string
  filePath: string
  fileName: string
  displayUrl: string
  isPdf: boolean
  pdfPage: number
  pdfTotalPages: number
  documentImage: DocumentImage | null
}

function toLocalFileUrl(absPath: string): string {
  const encoded = absPath.split('/').map((seg) => encodeURIComponent(seg)).join('/')
  return `localfile://${encoded}`
}

export default function DocumentView({
  onImageChange,
  showSidebar = true,
  sidebarWidth = 260,
  onLeftResizeStart,
}: DocumentViewProps) {
  const [openDocs, setOpenDocs] = useState<OpenDocument[]>([])
  const [activeDocId, setActiveDocId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [pdfRasterError, setPdfRasterError] = useState<string | null>(null)

  const activeDoc = openDocs.find((d) => d.id === activeDocId) || null

  const [draggedDocId, setDraggedDocId] = useState<string | null>(null)
  const [dragOverDocId, setDragOverDocId] = useState<string | null>(null)
  const [dropDocPosition, setDropDocPosition] = useState<'before' | 'after' | null>(null)

  const handleDocDragStart = (id: string, e: React.DragEvent) => {
    setDraggedDocId(id)
    e.dataTransfer.setData('text/plain', id)
  }

  const handleDocDragOver = (id: string, e: React.DragEvent) => {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const relativeY = e.clientY - rect.top
    const pos = relativeY < rect.height / 2 ? 'before' : 'after'
    setDragOverDocId(id)
    setDropDocPosition(pos)
  }

  const handleDocDragEnd = () => {
    setDraggedDocId(null)
    setDragOverDocId(null)
    setDropDocPosition(null)
  }

  const handleDocDrop = (targetId: string, e: React.DragEvent) => {
    e.preventDefault()
    if (!draggedDocId || draggedDocId === targetId) return

    const draggedDoc = openDocs.find((d) => d.id === draggedDocId)
    if (!draggedDoc) return

    const remainingDocs = openDocs.filter((d) => d.id !== draggedDocId)
    let insertIndex = remainingDocs.findIndex((d) => d.id === targetId)
    if (insertIndex !== -1) {
      if (dropDocPosition === 'after') {
        insertIndex += 1
      }
      const newDocs = [
        ...remainingDocs.slice(0, insertIndex),
        draggedDoc,
        ...remainingDocs.slice(insertIndex),
      ]
      setOpenDocs(newDocs)
    }
    handleDocDragEnd()
  }

  const openFile = async () => {
    const chosen = await window.electronAPI.openFile({
      filters: [
        { name: 'Maps & Documents', extensions: [...IMAGE_EXTS, 'pdf'] },
        { name: 'Images', extensions: IMAGE_EXTS },
        { name: 'PDF', extensions: ['pdf'] },
      ],
    })
    if (!chosen) return

    const name = chosen.split('/').pop() || chosen
    const ext = name.split('.').pop()?.toLowerCase() || ''
    const pdf = ext === 'pdf'
    const id = Math.random().toString(36).substring(2, 9)

    const newDoc: OpenDocument = {
      id,
      filePath: chosen,
      fileName: name,
      displayUrl: toLocalFileUrl(chosen),
      isPdf: pdf,
      pdfPage: 1,
      pdfTotalPages: 1,
      documentImage: null,
    }

    setLoading(true)
    setPdfRasterError(null)

    try {
      if (IMAGE_EXTS.includes(ext)) {
        const base64 = await window.electronAPI.readFileBase64(chosen)
        if (base64) {
          newDoc.documentImage = { base64, mimeType: MIME_MAP[ext] || 'image/png', fileName: name, filePath: chosen }
        }
      } else if (pdf) {
        const out = await rasterizePdfPage(chosen, 1)
        if (out) {
          newDoc.pdfTotalPages = out.totalPages
          newDoc.documentImage = {
            base64: out.base64,
            mimeType: 'image/png',
            fileName: name,
            filePath: chosen,
            page: 1,
            totalPages: out.totalPages,
          }
        } else {
          setPdfRasterError('Could not read the PDF.')
        }
      }

      setOpenDocs((prev) => [...prev, newDoc])
      setActiveDocId(id)
      onImageChange(newDoc.documentImage)
    } catch (e) {
      setPdfRasterError(`Failed to load document: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  const switchPdfPage = async (delta: number) => {
    if (!activeDoc || !activeDoc.isPdf || loading) return
    const next = Math.max(1, Math.min(activeDoc.pdfPage + delta, activeDoc.pdfTotalPages))
    if (next === activeDoc.pdfPage) return

    setLoading(true)
    setPdfRasterError(null)
    try {
      const out = await rasterizePdfPage(activeDoc.filePath, next)
      if (!out) {
        setPdfRasterError('Could not read the PDF.')
        return
      }

      const updatedDoc: OpenDocument = {
        ...activeDoc,
        pdfPage: next,
        pdfTotalPages: out.totalPages,
        documentImage: {
          base64: out.base64,
          mimeType: 'image/png',
          fileName: activeDoc.fileName,
          filePath: activeDoc.filePath,
          page: next,
          totalPages: out.totalPages,
        }
      }

      setOpenDocs((prev) => prev.map((d) => (d.id === activeDoc.id ? updatedDoc : d)))
      onImageChange(updatedDoc.documentImage)
    } catch (e) {
      setPdfRasterError(`PDF page change failed: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSelectDoc = (id: string) => {
    setActiveDocId(id)
    const doc = openDocs.find((d) => d.id === id)
    onImageChange(doc ? doc.documentImage : null)
    setPdfRasterError(null)
  }

  const handleCloseDoc = (id: string) => {
    const nextDocs = openDocs.filter((d) => d.id !== id)
    setOpenDocs(nextDocs)
    if (activeDocId === id) {
      const nextActiveId = nextDocs.length > 0 ? nextDocs[0].id : null
      setActiveDocId(nextActiveId)
      const doc = nextDocs.find((d) => d.id === nextActiveId)
      onImageChange(doc ? doc.documentImage : null)
    }
    setPdfRasterError(null)
  }

  /* Resize is handled by the global panel resize handle in App.tsx */

  return (
    <div className="doc-view">
      {/* ── Document List Sidebar (always visible) ── */}
      {showSidebar && (
        <div className="doc-sidebar" style={{ width: sidebarWidth, flex: `0 0 ${sidebarWidth}px` }}>
          <div className="doc-sidebar-toolbar">
            <button className="doc-sidebar-add-btn" onClick={openFile} title="Open document">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 6 }}>
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              Open File
            </button>
          </div>

          <div className="doc-sidebar-list">
            {openDocs.length === 0 ? (
              <div className="doc-sidebar-empty">
                <div className="empty-icon-container-sm">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                </div>
                <p className="title">No documents open</p>
                <p className="hint">Open a map image or PDF to analyze.</p>
              </div>
            ) : (
              openDocs.map((doc) => (
                <div
                  key={doc.id}
                  className={`doc-sidebar-item ${doc.id === activeDocId ? 'active' : ''} ${dragOverDocId === doc.id ? `drag-over-${dropDocPosition}` : ''}`}
                  onClick={() => handleSelectDoc(doc.id)}
                  draggable={true}
                  onDragStart={(e) => handleDocDragStart(doc.id, e)}
                  onDragOver={(e) => handleDocDragOver(doc.id, e)}
                  onDrop={(e) => handleDocDrop(doc.id, e)}
                  onDragEnd={handleDocDragEnd}
                  style={{ cursor: 'grab' }}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="doc-sidebar-item-icon">
                    {doc.isPdf ? (
                      <>
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                      </>
                    ) : (
                      <>
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        <circle cx="8.5" cy="8.5" r="1.5"></circle>
                        <polyline points="21 15 16 10 5 21"></polyline>
                      </>
                    )}
                  </svg>
                  <span className="doc-sidebar-item-name" title={doc.filePath}>
                    {doc.fileName}
                  </span>
                  <button
                    className="doc-sidebar-item-close"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCloseDoc(doc.id)
                    }}
                    title="Close document"
                    style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {showSidebar && onLeftResizeStart && (
        <div className="resize-handle" onMouseDown={onLeftResizeStart} />
      )}

      {/* ── Detail Pane ── */}
      <div className="doc-detail-pane">
        {activeDoc === null ? (
          <div className="doc-empty-detail">
            <div className="doc-empty-detail-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2">
                <path d="M9 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8l4 4v4" />
                <path d="M9 20h9a2 2 0 0 0 2-2v-7" />
                <rect x="9" y="14" width="8" height="6" rx="1" />
              </svg>
            </div>
            <p className="doc-empty-detail-title">No document open</p>
            <p className="doc-empty-detail-hint">
              Open a map image or PDF to analyse it with the AI assistant.
            </p>
            <button className="doc-empty-open-btn" onClick={openFile}>
              Open File
            </button>
          </div>
        ) : (
          <>
            <div className="doc-toolbar">
              <span className="doc-filename" title={activeDoc.filePath}>
                {activeDoc.fileName}
              </span>
              {activeDoc.isPdf && (
                <span className="doc-pdf-note">
                  PDF — AI sees page {activeDoc.pdfPage} of {activeDoc.pdfTotalPages}
                </span>
              )}
              {activeDoc.isPdf && activeDoc.pdfTotalPages > 1 && (
                <span className="doc-pdf-pager">
                  <button
                    className="doc-pdf-pager-btn"
                    onClick={() => switchPdfPage(-1)}
                    disabled={loading || activeDoc.pdfPage <= 1}
                    title="Previous page"
                  >
                    ‹
                  </button>
                  <span className="doc-pdf-pager-label">
                    {activeDoc.pdfPage} / {activeDoc.pdfTotalPages}
                  </span>
                  <button
                    className="doc-pdf-pager-btn"
                    onClick={() => switchPdfPage(1)}
                    disabled={loading || activeDoc.pdfPage >= activeDoc.pdfTotalPages}
                    title="Next page"
                  >
                    ›
                  </button>
                </span>
              )}
              {loading && <span className="doc-loading-inline">Rendering…</span>}
              {pdfRasterError && <span className="doc-loading-inline doc-error">{pdfRasterError}</span>}
            </div>

            <div className="doc-content">
              {activeDoc.displayUrl && (
                activeDoc.isPdf ? (
                  <iframe src={activeDoc.displayUrl} className="doc-pdf" title={activeDoc.fileName} />
                ) : (
                  <img src={activeDoc.displayUrl} alt={activeDoc.fileName} className="doc-img" />
                )
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
