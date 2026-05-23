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

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp']
// Cap rasterization size — vision works fine at 1.5x scale, and bigger
// canvases blow up base64 payloads.
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
  // Decode base64 → Uint8Array (pdfjs accepts a typed-array data source).
  const binary = atob(base64Pdf)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)

  const pdfjs = await import('pdfjs-dist')
  // Disable the worker — we run inside a chromium renderer in Electron and
  // the bundled worker URL doesn't survive electron-vite's prod build. The
  // main-thread fallback is slower but works for one-off planning PDFs.
  type GlobalOptions = { disableWorker?: boolean }
  ;(pdfjs as unknown as { GlobalWorkerOptions: GlobalOptions }).GlobalWorkerOptions.disableWorker = true

  const doc = await pdfjs.getDocument({ data: bytes }).promise
  const total = doc.numPages
  const page = await doc.getPage(Math.max(1, Math.min(pageNumber, total)))
  let viewport = page.getViewport({ scale: PDF_RASTER_SCALE })
  // Clamp the longer axis so we don't hand vision a 6000px image.
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
  const [filePath, setFilePath] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [displayUrl, setDisplayUrl] = useState<string | null>(null)
  const [isPdf, setIsPdf] = useState(false)
  const [loading, setLoading] = useState(false)
  const [pdfPage, setPdfPage] = useState(1)
  const [pdfTotalPages, setPdfTotalPages] = useState(1)
  const [pdfRasterError, setPdfRasterError] = useState<string | null>(null)

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

    setFilePath(chosen)
    setFileName(name)
    setIsPdf(pdf)
    setDisplayUrl(null)
    setPdfRasterError(null)
    setPdfPage(1)
    setPdfTotalPages(1)
    onImageChange(null)

    setDisplayUrl(toLocalFileUrl(chosen))

    if (IMAGE_EXTS.includes(ext)) {
      setLoading(true)
      const base64 = await window.electronAPI.readFileBase64(chosen)
      setLoading(false)
      if (base64) {
        const mimes: Record<string, string> = {
          png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
          webp: 'image/webp', gif: 'image/gif', bmp: 'image/bmp',
        }
        onImageChange({ base64, mimeType: mimes[ext] || 'image/png', fileName: name })
      }
      return
    }

    if (pdf) {
      setLoading(true)
      try {
        const out = await rasterizePdfPage(chosen, 1)
        if (out) {
          setPdfTotalPages(out.totalPages)
          onImageChange({
            base64: out.base64,
            mimeType: 'image/png',
            fileName: name,
            page: 1,
            totalPages: out.totalPages,
          })
        } else {
          setPdfRasterError('Could not read the PDF.')
        }
      } catch (e) {
        setPdfRasterError(`PDF rasterization failed: ${(e as Error).message}`)
      } finally {
        setLoading(false)
      }
    }
  }

  const switchPdfPage = async (delta: number) => {
    if (!filePath || !isPdf || loading) return
    const next = Math.max(1, Math.min(pdfPage + delta, pdfTotalPages))
    if (next === pdfPage) return
    setLoading(true)
    setPdfRasterError(null)
    try {
      const out = await rasterizePdfPage(filePath, next)
      if (!out) {
        setPdfRasterError('Could not read the PDF.')
        return
      }
      setPdfPage(next)
      setPdfTotalPages(out.totalPages)
      onImageChange({
        base64: out.base64,
        mimeType: 'image/png',
        fileName,
        page: next,
        totalPages: out.totalPages,
      })
    } catch (e) {
      setPdfRasterError(`PDF rasterization failed: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  if (!filePath) {
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
      <div className="doc-toolbar">
        <span className="doc-filename" title={filePath}>{fileName}</span>
        {isPdf && (
          <span className="doc-pdf-note">
            PDF — AI sees page {pdfPage}{pdfTotalPages > 1 ? ` of ${pdfTotalPages}` : ''}
          </span>
        )}
        {isPdf && pdfTotalPages > 1 && (
          <span className="doc-pdf-pager">
            <button
              className="doc-pdf-pager-btn"
              onClick={() => switchPdfPage(-1)}
              disabled={loading || pdfPage <= 1}
              title="Previous page"
            >
              ‹
            </button>
            <span className="doc-pdf-pager-label">{pdfPage} / {pdfTotalPages}</span>
            <button
              className="doc-pdf-pager-btn"
              onClick={() => switchPdfPage(1)}
              disabled={loading || pdfPage >= pdfTotalPages}
              title="Next page"
            >
              ›
            </button>
          </span>
        )}
        {loading && <span className="doc-loading-inline">Rendering…</span>}
        {pdfRasterError && <span className="doc-loading-inline doc-error">{pdfRasterError}</span>}
        <button className="doc-change-btn" onClick={openFile}>Change…</button>
      </div>
      <div className="doc-content">
        {displayUrl && (
          isPdf
            ? <iframe src={displayUrl} className="doc-pdf" title={fileName} />
            : <img src={displayUrl} alt={fileName} className="doc-img" />
        )}
      </div>
    </div>
  )
}
