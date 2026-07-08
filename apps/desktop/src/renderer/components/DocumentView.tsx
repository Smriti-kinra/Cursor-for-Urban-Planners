import { useState } from 'react'
import './DocumentView.css'

export interface DocumentImage {
  base64: string
  mimeType: string
  fileName: string
  /** For multi-page sources, the page number that was rasterized (1-indexed). */
  page?: number
  /** For multi-page sources, the total number of pages. */
  totalPages?: number
}

interface DocumentViewProps {
  onImageChange: (img: DocumentImage | null) => void
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

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp']
const PDF_RASTER_SCALE = 1.5
const PDF_MAX_PIXELS = 2200

function toLocalFileUrl(absPath: string): string {
  const encoded = absPath.split('/').map((seg) => encodeURIComponent(seg)).join('/')
  return `localfile://${encoded}`
}

async function rasterizePdfPage(
  absPath: string,
  pageNumber: number,
): Promise<{ base64: string; totalPages: number } | null> {
  const base64Pdf = await window.electronAPI.readFileBase64(absPath)
  if (!base64Pdf) return null
  const binary = atob(base64Pdf)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)

  const pdfjs = await import('pdfjs-dist')
  type GlobalOptions = { disableWorker?: boolean }
  ;(pdfjs as unknown as { GlobalWorkerOptions: GlobalOptions }).GlobalWorkerOptions.disableWorker = true

  const doc = await pdfjs.getDocument({ data: bytes }).promise
  const total = doc.numPages
  const page = await doc.getPage(Math.max(1, Math.min(pageNumber, total)))
  let viewport = page.getViewport({ scale: PDF_RASTER_SCALE })
  const longer = Math.max(viewport.width, viewport.height)
  if (longer > PDF_MAX_PIXELS) {
    const adj = PDF_MAX_PIXELS / longer
    viewport = page.getViewport({ scale: PDF_RASTER_SCALE * adj })
  }

  const canvas = document.createElement('canvas')
  canvas.width = Math.ceil(viewport.width)
  canvas.height = Math.ceil(viewport.height)
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  await page.render({ canvasContext: ctx, viewport, canvas }).promise

  const dataUrl = canvas.toDataURL('image/png')
  const base64 = dataUrl.split(',')[1] || ''
  return { base64, totalPages: total }
}

export default function DocumentView({ onImageChange }: DocumentViewProps) {
  const [openDocs, setOpenDocs] = useState<OpenDocument[]>([])
  const [activeDocId, setActiveDocId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [pdfRasterError, setPdfRasterError] = useState<string | null>(null)

  const activeDoc = openDocs.find((d) => d.id === activeDocId) || null

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
          const mimes: Record<string, string> = {
            png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
            webp: 'image/webp', gif: 'image/gif', bmp: 'image/bmp',
          }
          newDoc.documentImage = { base64, mimeType: mimes[ext] || 'image/png', fileName: name }
        }
      } else if (pdf) {
        const out = await rasterizePdfPage(chosen, 1)
        if (out) {
          newDoc.pdfTotalPages = out.totalPages
          newDoc.documentImage = {
            base64: out.base64,
            mimeType: 'image/png',
            fileName: name,
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

  if (openDocs.length === 0) {
    return (
      <div className="doc-empty">
        <div className="doc-empty-icon">🗺</div>
        <p className="doc-empty-title">No document open</p>
        <p className="doc-empty-hint">
          Open a saved map image or PDF to analyze it with the AI assistant.
          The assistant can see images and answer planning questions about them.
        </p>
        <button className="doc-open-btn" onClick={openFile}>Open file…</button>
      </div>
    )
  }

  return (
    <div className="doc-view">
      {/* ── Document Tabs ── */}
      <div className="doc-tabs-bar">
        {openDocs.map((doc) => (
          <div
            key={doc.id}
            className={`doc-tab ${doc.id === activeDocId ? 'active' : ''}`}
            onClick={() => handleSelectDoc(doc.id)}
          >
            <span className="doc-tab-name" title={doc.filePath}>
              {doc.fileName}
            </span>
            <button
              className="doc-tab-close"
              onClick={(e) => {
                e.stopPropagation()
                handleCloseDoc(doc.id)
              }}
              title="Close document"
            >
              ×
            </button>
          </div>
        ))}
        <button className="doc-tab-add" onClick={openFile} title="Open another document">
          + Open File
        </button>
      </div>

      {activeDoc && (
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
  )
}
