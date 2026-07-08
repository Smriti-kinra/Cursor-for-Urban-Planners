import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Geometry } from 'geojson'
import 'pannellum/build/pannellum.css'
import 'pannellum/build/pannellum.js'
import './StreetViewWorkspace.css'

declare global {
  interface Window {
    pannellum?: {
      viewer: (el: HTMLElement, config: Record<string, unknown>) => { destroy: () => void }
    }
  }
}

export interface StreetViewTarget {
  lng: number
  lat: number
  label?: string
}

export interface RoadInspectionTarget {
  geometry: Geometry
  name?: string
}

interface StreetViewMeta {
  found: boolean
  pano_id?: string | null
  lat?: number | null
  lon?: number | null
  date?: string | null
  heading?: number | null
  address?: string | null
  error?: string
}

interface RoadSamplePoint {
  id: string
  distance_m: number
  lat: number
  lng: number
}

interface StreetViewArtifactResult {
  found: boolean
  metadata?: StreetViewMeta
  artifact?: {
    id: number
    title: string
    meta: string | null
  }
  artifact_id?: number
  download_url?: string
  error?: string
}

interface GalleryItem {
  point: RoadSamplePoint
  status: 'pending' | 'loading' | 'done' | 'missing' | 'error'
  selected: boolean
  artifactId?: number
  imageUrl?: string
  address?: string | null
  captureDate?: string | null
  notes: string
  error?: string
}

interface StreetViewWorkspaceProps {
  target: StreetViewTarget | null
  roadTarget: RoadInspectionTarget | null
  onArtifactsChanged?: () => void
  onClose?: () => void
}

const API = 'http://localhost:8765/api/streetview'
const ARTIFACT_API = 'http://localhost:8765/api/artifacts'

function coordinateLabel(lat?: number | null, lng?: number | null): string {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return 'Unknown coordinates'
  return `${Number(lat).toFixed(5)}, ${Number(lng).toFixed(5)}`
}

function captionFromMeta(meta: StreetViewMeta | null): string {
  const address = meta?.address || 'Street View location'
  const coords = coordinateLabel(meta?.lat, meta?.lon)
  const date = meta?.date ? `, captured ${meta.date}` : ''
  return `${address} (${coords})${date}.`
}

function parseArtifactMeta(value: string | null): Record<string, unknown> {
  if (!value) return {}
  try {
    return JSON.parse(value)
  } catch {
    return {}
  }
}

export default function StreetViewWorkspace({
  target,
  roadTarget,
  onArtifactsChanged,
  onClose,
}: StreetViewWorkspaceProps) {
  const [meta, setMeta] = useState<StreetViewMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [googleKey, setGoogleKey] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [lastArtifactId, setLastArtifactId] = useState<number | null>(null)
  const [reportStatus, setReportStatus] = useState<string | null>(null)
  const [intervalM, setIntervalM] = useState(30)
  const [gallery, setGallery] = useState<GalleryItem[]>([])
  const [galleryBusy, setGalleryBusy] = useState(false)
  const [galleryError, setGalleryError] = useState<string | null>(null)
  const viewerHostRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<{ destroy: () => void } | null>(null)

  useEffect(() => {
    window.electronAPI.getGoogleMapsKey().then((key) => {
      setGoogleKey(key || '')
    }).catch(() => setGoogleKey(''))
  }, [])

  useEffect(() => {
    if (!target || googleKey === null) {
      setMeta(null)
      setError(null)
      setLastArtifactId(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setMeta(null)
    setLastArtifactId(null)
    const headers: Record<string, string> = {}
    if (googleKey) headers['x-google-maps-key'] = googleKey
    fetch(`${API}/meta?lat=${target.lat}&lng=${target.lng}`, { headers })
      .then((r) => r.json())
      .then((d: StreetViewMeta) => { if (!cancelled) setMeta(d) })
      .catch((e) => { if (!cancelled) setError(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [target, googleKey])

  useEffect(() => {
    if (!meta?.found || !target || !viewerHostRef.current || googleKey === null) return
    if (!window.pannellum) {
      setError('360 degree viewer failed to load.')
      return
    }
    const host = viewerHostRef.current
    const keyQuery = googleKey ? `&google_maps_api_key=${encodeURIComponent(googleKey)}` : ''
    const viewer = window.pannellum.viewer(host, {
      type: 'equirectangular',
      panorama: `${API}/pano?lat=${target.lat}&lng=${target.lng}&zoom=3${keyQuery}`,
      autoLoad: true,
      showControls: true,
      compass: true,
      crossOrigin: 'anonymous',
    })
    viewerRef.current = viewer
    return () => {
      try { viewer.destroy() } catch { /* ignore pannellum teardown noise */ }
      viewerRef.current = null
    }
  }, [meta, target, googleKey])

  const headers = useMemo(() => {
    const h: Record<string, string> = { 'Content-Type': 'application/json' }
    if (googleKey) h['x-google-maps-key'] = googleKey
    return h
  }, [googleKey])

  const saveCurrentImage = useCallback(async (): Promise<StreetViewArtifactResult | null> => {
    if (!target) return null
    setSaving(true)
    setReportStatus(null)
    try {
      const resp = await fetch(`${API}/image`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          lat: target.lat,
          lng: target.lng,
          title: meta?.address || target.label || `Street View ${coordinateLabel(target.lat, target.lng)}`,
        }),
      })
      const data: StreetViewArtifactResult = await resp.json()
      if (!resp.ok || !data.found) {
        setReportStatus(data.error || 'No Street View image could be saved here.')
        return null
      }
      const id = data.artifact_id || data.artifact?.id || null
      setLastArtifactId(id)
      onArtifactsChanged?.()
      return data
    } catch (e) {
      setReportStatus(`Street View save failed: ${String(e)}`)
      return null
    } finally {
      setSaving(false)
    }
  }, [target, headers, meta, onArtifactsChanged])

  const downloadCurrentImage = useCallback(async () => {
    const result = await saveCurrentImage()
    const id = result?.artifact_id || result?.artifact?.id
    if (!id) return
    const a = document.createElement('a')
    a.href = `${ARTIFACT_API}/${id}/download`
    a.download = `street-view-${id}.jpg`
    a.click()
  }, [saveCurrentImage])

  const addImagesToReport = useCallback(async (images: Array<Record<string, unknown>>, title: string) => {
    if (!images.length) return
    setReportStatus(null)
    try {
      const resp = await fetch(`${API}/report`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ title, images }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setReportStatus('Added to an editable report artifact.')
      onArtifactsChanged?.()
    } catch (e) {
      setReportStatus(`Report insert failed: ${String(e)}`)
    }
  }, [headers, onArtifactsChanged])

  const addCurrentToReport = useCallback(async () => {
    let artifactId = lastArtifactId
    if (!artifactId) {
      const result = await saveCurrentImage()
      artifactId = result?.artifact_id || result?.artifact?.id || null
    }
    if (!artifactId) return
    await addImagesToReport(
      [{
        artifact_id: artifactId,
        lat: meta?.lat ?? target?.lat,
        lng: meta?.lon ?? target?.lng,
        address: meta?.address,
        capture_date: meta?.date,
        caption: captionFromMeta(meta),
      }],
      `Street View - ${meta?.address || target?.label || coordinateLabel(target?.lat, target?.lng)}`,
    )
  }, [addImagesToReport, lastArtifactId, meta, saveCurrentImage, target])

  const runRoadInspection = useCallback(async () => {
    if (!roadTarget) return
    setGalleryBusy(true)
    setGalleryError(null)
    setGallery([])
    setReportStatus(null)
    try {
      const sampleResp = await fetch(`${API}/road-inspection`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ geometry: roadTarget.geometry, interval_m: intervalM }),
      })
      const sampled: { points?: RoadSamplePoint[]; error?: string } = await sampleResp.json()
      if (!sampleResp.ok || !sampled.points?.length) {
        throw new Error(sampled.error || 'No sample points could be generated for this road.')
      }

      setGallery(sampled.points.map((point) => ({ point, status: 'pending', selected: false, notes: '' })))
      for (const point of sampled.points) {
        setGallery((prev) => prev.map((item) =>
          item.point.id === point.id ? { ...item, status: 'loading' } : item,
        ))
        try {
          const resp = await fetch(`${API}/image`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
              lat: point.lat,
              lng: point.lng,
              title: `${roadTarget.name || 'Road inspection'} - ${Math.round(point.distance_m)} m`,
            }),
          })
          const data: StreetViewArtifactResult = await resp.json()
          if (!resp.ok || !data.found) {
            setGallery((prev) => prev.map((item) =>
              item.point.id === point.id ? { ...item, status: 'missing' } : item,
            ))
            continue
          }
          const artifactId = data.artifact_id || data.artifact?.id
          const parsedMeta = parseArtifactMeta(data.artifact?.meta || null)
          setGallery((prev) => prev.map((item) =>
            item.point.id === point.id
              ? {
                  ...item,
                  status: 'done',
                  selected: true,
                  artifactId,
                  imageUrl: artifactId ? `${ARTIFACT_API}/${artifactId}/download` : undefined,
                  address: data.metadata?.address || String(parsedMeta.address || '') || null,
                  captureDate: data.metadata?.date || String(parsedMeta.capture_date || '') || null,
                }
              : item,
          ))
          onArtifactsChanged?.()
        } catch (e) {
          setGallery((prev) => prev.map((item) =>
            item.point.id === point.id ? { ...item, status: 'error', error: String(e) } : item,
          ))
        }
      }
    } catch (e) {
      setGalleryError(String(e))
    } finally {
      setGalleryBusy(false)
    }
  }, [headers, intervalM, onArtifactsChanged, roadTarget])

  const updateGalleryNotes = useCallback(async (artifactId: number | undefined, notes: string) => {
    setGallery((prev) => prev.map((item) =>
      item.artifactId === artifactId ? { ...item, notes } : item,
    ))
    if (!artifactId) return
    const item = gallery.find((g) => g.artifactId === artifactId)
    const existing = item?.artifactId ? item : null
    try {
      const current = await fetch(`${ARTIFACT_API}/${artifactId}`).then((r) => r.ok ? r.json() : null)
      const currentMeta = parseArtifactMeta(current?.meta || null)
      await fetch(`${ARTIFACT_API}/${artifactId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meta: { ...currentMeta, planner_notes: notes } }),
      })
      if (existing) onArtifactsChanged?.()
    } catch {
      /* Keep notes in the gallery even if the artifact update fails. */
    }
  }, [gallery, onArtifactsChanged])

  const addSelectedGalleryToReport = useCallback(async () => {
    const done = gallery.filter((item) => item.selected && item.status === 'done' && item.artifactId)
    await addImagesToReport(
      done.map((item, index) => ({
        artifact_id: item.artifactId,
        lat: item.point.lat,
        lng: item.point.lng,
        address: item.address,
        capture_date: item.captureDate,
        planner_notes: item.notes,
        caption: `Figure ${index + 1}. ${item.address || roadTarget?.name || 'Road inspection point'} at ${Math.round(item.point.distance_m)} m.`,
      })),
      `${roadTarget?.name || 'Road'} Street View Inspection`,
    )
  }, [addImagesToReport, gallery, roadTarget])

  const addFullGalleryToReport = useCallback(async () => {
    const done = gallery.filter((item) => item.status === 'done' && item.artifactId)
    await addImagesToReport(
      done.map((item, index) => ({
        artifact_id: item.artifactId,
        lat: item.point.lat,
        lng: item.point.lng,
        address: item.address,
        capture_date: item.captureDate,
        planner_notes: item.notes,
        caption: `Figure ${index + 1}. ${item.address || roadTarget?.name || 'Road inspection point'} at ${Math.round(item.point.distance_m)} m.`,
      })),
      `${roadTarget?.name || 'Road'} Street View Inspection Session`,
    )
  }, [addImagesToReport, gallery, roadTarget])

  if (!target && !roadTarget) {
    return (
      <div className="sv-workspace sv-empty">
        <div className="sv-empty-title">Street View Workspace</div>
        <div className="sv-empty-text">
          Use the map Street View tool, right-click a location, select a marker, search for a place,
          or inspect a road layer.
        </div>
      </div>
    )
  }

  const doneCount = gallery.filter((item) => item.status === 'done').length
  const selectedDoneCount = gallery.filter((item) => item.selected && item.status === 'done').length
  const processedCount = gallery.filter((item) => item.status !== 'pending').length
  const galleryTotal = gallery.length

  return (
    <div className="sv-workspace">
      <div className="sv-panel-header">
        <div>
          <div className="sv-eyebrow">Street View</div>
          <div className="sv-heading">
            {meta?.address || target?.label || (target ? coordinateLabel(target.lat, target.lng) : roadTarget?.name || 'Road inspection')}
          </div>
        </div>
        {onClose && <button className="sv-icon-btn" onClick={onClose} title="Close Street View">x</button>}
      </div>

      {target && (
        <section className="sv-section">
          <div className="sv-viewer-shell">
            {loading && <div className="sv-status">Loading Street View...</div>}
            {!loading && error && <div className="sv-status">Street View lookup failed. {error}</div>}
            {!loading && meta && !meta.found && (
              <div className="sv-status">No Street View imagery is available near this location.</div>
            )}
            {!loading && meta?.found && <div ref={viewerHostRef} className="sv-viewer" />}
          </div>

          <div className="sv-meta-grid">
            <div><span>Address</span><strong>{meta?.address || 'Nearest panorama'}</strong></div>
            <div><span>Coordinates</span><strong>{coordinateLabel(meta?.lat ?? target.lat, meta?.lon ?? target.lng)}</strong></div>
            <div><span>Capture Date</span><strong>{meta?.date || 'Not available'}</strong></div>
          </div>

          <div className="sv-actions">
            <button onClick={downloadCurrentImage} disabled={!meta?.found || saving}>
              Download Image
            </button>
            <button onClick={saveCurrentImage} disabled={!meta?.found || saving}>
              Save to Artifacts
            </button>
            <button onClick={addCurrentToReport} disabled={!meta?.found || saving}>
              Add to Report
            </button>
          </div>
          {lastArtifactId && <div className="sv-note">Saved as artifact #{lastArtifactId}.</div>}
          {reportStatus && <div className="sv-note">{reportStatus}</div>}
        </section>
      )}

      {roadTarget && (
        <section className="sv-section sv-road-section">
          <div className="sv-section-head">
            <div>
              <div className="sv-eyebrow">Road Inspection</div>
              <div className="sv-subheading">{roadTarget.name || 'Selected road'}</div>
            </div>
            <label className="sv-interval">
              <span>Interval</span>
              <input
                type="number"
                min={5}
                max={500}
                value={intervalM}
                onChange={(e) => setIntervalM(Number(e.target.value) || 30)}
              />
              <span>m</span>
            </label>
          </div>
          <div className="sv-actions">
            <button onClick={runRoadInspection} disabled={galleryBusy}>Inspect Road</button>
            <button onClick={addSelectedGalleryToReport} disabled={selectedDoneCount === 0}>Add Selected to Report</button>
            <button onClick={addFullGalleryToReport} disabled={doneCount === 0}>Add Session to Report</button>
          </div>
          {galleryTotal > 0 && (
            <div className="sv-progress">
              <div className="sv-progress-bar" style={{ width: `${Math.round((processedCount / galleryTotal) * 100)}%` }} />
              <span>{processedCount}/{galleryTotal} processed, {doneCount} saved</span>
            </div>
          )}
          {galleryError && <div className="sv-note sv-error">{galleryError}</div>}
          <div className="sv-gallery">
            {gallery.map((item) => (
              <article key={item.point.id} className="sv-gallery-item">
                {item.imageUrl ? (
                  <img src={item.imageUrl} alt={item.address || 'Street View'} />
                ) : (
                  <div className="sv-gallery-placeholder">{item.status}</div>
                )}
                <div className="sv-gallery-body">
                  <label className="sv-gallery-select">
                    <input
                      type="checkbox"
                      checked={item.selected}
                      disabled={item.status !== 'done'}
                      onChange={(e) => {
                        const selected = e.target.checked
                        setGallery((prev) => prev.map((g) =>
                          g.point.id === item.point.id ? { ...g, selected } : g,
                        ))
                      }}
                    />
                    <span>Include in report</span>
                  </label>
                  <strong>{item.address || `${Math.round(item.point.distance_m)} m`}</strong>
                  <span>{coordinateLabel(item.point.lat, item.point.lng)}</span>
                  <span>{item.captureDate || 'Capture date unavailable'}</span>
                  <textarea
                    placeholder="Planner notes"
                    value={item.notes}
                    onChange={(e) => updateGalleryNotes(item.artifactId, e.target.value)}
                    disabled={item.status !== 'done'}
                  />
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
