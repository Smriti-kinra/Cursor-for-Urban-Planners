import { useState } from 'react'
import './DocumentView.css'

export interface DocumentImage {
  base64: string
  mimeType: string
  fileName: string
}

interface DocumentViewProps {
  onImageChange: (img: DocumentImage | null) => void
}

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp']

// Convert an absolute path to a localfile:// URL the renderer can safely load.
// The localfile:// protocol is a privileged custom scheme registered in main/index.ts
// that proxies to file://, bypassing cross-origin restrictions in dev mode.
function toLocalFileUrl(absPath: string): string {
  // Encode each path segment so spaces / special chars survive the URL round-trip.
  const encoded = absPath.split('/').map((seg) => encodeURIComponent(seg)).join('/')
  return `localfile://${encoded}`
}

export default function DocumentView({ onImageChange }: DocumentViewProps) {
  const [filePath, setFilePath] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [displayUrl, setDisplayUrl] = useState<string | null>(null)
  const [isPdf, setIsPdf] = useState(false)
  const [loading, setLoading] = useState(false)

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
    onImageChange(null)

    // Build the localfile:// display URL
    setDisplayUrl(toLocalFileUrl(chosen))

    // For AI vision, also read as base64 (images only)
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
        {isPdf && <span className="doc-pdf-note">PDF — display only (AI sees images only)</span>}
        {loading && <span className="doc-loading-inline">Reading…</span>}
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
