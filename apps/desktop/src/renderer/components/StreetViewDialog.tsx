import { useEffect, useRef, useState } from 'react'
import 'pannellum/build/pannellum.css'
// @ts-expect-error pannellum ships no types
import 'pannellum/build/pannellum.js'
import './StreetViewDialog.css'

// pannellum attaches itself to window.
declare global {
  interface Window {
    pannellum?: {
      viewer: (el: HTMLElement, config: Record<string, unknown>) => { destroy: () => void }
    }
  }
}

interface StreetViewMeta {
  found: boolean
  pano_id?: string
  date?: string | null
  address?: string | null
  error?: string
}

interface StreetViewDialogProps {
  target: { lng: number; lat: number } | null
  onClose: () => void
}

const API = 'http://localhost:8765/api/streetview'

export default function StreetViewDialog({ target, onClose }: StreetViewDialogProps) {
  const [meta, setMeta] = useState<StreetViewMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const viewerHostRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<{ destroy: () => void } | null>(null)

  // Escape to close.
  useEffect(() => {
    if (!target) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [target, onClose])

  // Fetch metadata when target changes.
  useEffect(() => {
    if (!target) { setMeta(null); setError(null); return }
    let cancelled = false
    setLoading(true)
    setError(null)
    setMeta(null)
    fetch(`${API}/meta?lat=${target.lat}&lng=${target.lng}`)
      .then((r) => r.json())
      .then((d: StreetViewMeta) => { if (!cancelled) setMeta(d) })
      .catch((e) => { if (!cancelled) setError(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [target])

  // Init pannellum when we have a found panorama. Request the pano image by
  // lat/lng (the backend rediscovers the panorama from coordinates).
  useEffect(() => {
    if (!meta?.found || !target || !viewerHostRef.current) return
    if (!window.pannellum) { setError('360° viewer failed to load.'); return }
    const host = viewerHostRef.current
    const viewer = window.pannellum.viewer(host, {
      type: 'equirectangular',
      panorama: `${API}/pano?lat=${target.lat}&lng=${target.lng}&zoom=3`,
      autoLoad: true,
      showControls: true,
      crossOrigin: 'anonymous',
    })
    viewerRef.current = viewer
    return () => {
      try { viewer.destroy() } catch { /* ignore */ }
      viewerRef.current = null
    }
  }, [meta, target])

  if (!target) return null

  return (
    <div className="sv-overlay" onClick={onClose}>
      <div className="sv-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="sv-header">
          <div className="sv-title">
            📍 {meta?.address || `${target.lat.toFixed(5)}, ${target.lng.toFixed(5)}`}
            {meta?.date ? <span className="sv-date"> · {meta.date}</span> : null}
          </div>
          <button className="sv-close" onClick={onClose}>✕</button>
        </div>
        <div className="sv-body">
          {loading && <div className="sv-status">Loading Street View…</div>}
          {!loading && error && <div className="sv-status">⚠ {error}</div>}
          {!loading && meta && !meta.found && (
            <div className="sv-status">No Street View imagery here.</div>
          )}
          {!loading && meta?.found && (
            <div ref={viewerHostRef} className="sv-viewer" />
          )}
        </div>
      </div>
    </div>
  )
}
