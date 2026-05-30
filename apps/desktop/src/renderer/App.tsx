import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import * as turf from '@turf/turf'
import type { Feature, FeatureCollection, Geometry, Polygon, MultiPolygon } from 'geojson'
import MapView, { type MapViewHandle } from './components/MapView'
import FileTree from './components/FileTree'
import ChatPanel from './components/ChatPanel'
import StreetViewDialog from './components/StreetViewDialog'
import ArtifactsPanel from './components/ArtifactsPanel'
import LayerPanel from './components/LayerPanel'
import SymbologyPanel from './components/SymbologyPanel'
import Legend from './components/Legend'
import BookmarkPanel from './components/BookmarkPanel'
import ExportPanel from './components/ExportPanel'
import ZoningPanel from './components/ZoningPanel'
import DocumentView, { type DocumentImage } from './components/DocumentView'
import ErrorBoundary from './components/ErrorBoundary'
import {
  GeoJSONLayer,
  MapViewState,
  Conversation,
  MapAction,
  MapContext,
  ProjectData,
  LAYER_COLORS,
  MapBookmark,
  BoundaryGeometry,
  LayerGeometryData,
  LayerStyleSpec,
} from './types'
import {
  computeBreaks,
  buildCategories,
  rampColorsForClasses,
  DEFAULT_RAMP,
} from './lib/classify'

type AppMode = 'map' | 'document'
type LeftTab = 'files' | 'layers' | 'bookmarks' | 'export' | 'zoning'
type RightTab = 'chat' | 'artifacts'

function genId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function App() {
  const [appMode, setAppMode] = useState<AppMode>('map')
  const [documentImage, setDocumentImage] = useState<DocumentImage | null>(null)
  const [workspacePath, setWorkspacePath] = useState<string | null>(null)
  const [activeLeftTab, setActiveLeftTab] = useState<LeftTab>('files')
  const [activeRightTab, setActiveRightTab] = useState<RightTab>('chat')
  const [stylingLayerId, setStylingLayerId] = useState<string | null>(null)
  const [convertingFile, setConvertingFile] = useState<string | null>(null)
  const [convertError, setConvertError] = useState<string | null>(null)

  const [layers, setLayers] = useState<GeoJSONLayer[]>([])
  const [mapViewState, setMapViewState] = useState<MapViewState>({
    center: [76.7794, 30.7333],
    zoom: 13,
    bearing: 0,
    pitch: 0,
  })
  const [basemap, setBasemap] = useState('street')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [mapActions, setMapActions] = useState<MapAction[]>([])
  const [streetViewTarget, setStreetViewTarget] = useState<{ lng: number; lat: number } | null>(null)
  const [injectedMessage, setInjectedMessage] = useState<{ text: string; nonce: number } | null>(null)
  const [bookmarks, setBookmarks] = useState<MapBookmark[]>([])
  const [mapBounds, setMapBounds] = useState<{
    west: number
    south: number
    east: number
    north: number
  } | null>(null)
  const [artifactsRevision, setArtifactsRevision] = useState(0)

  const mapViewRef = useRef<MapViewHandle>(null)
  const bookmarksRef = useRef<MapBookmark[]>([])
  const mapBoundsRef = useRef<typeof mapBounds>(null)
  const saveProjectRef = useRef<(force?: boolean) => Promise<void>>(async () => {})

  const colorIndexRef = useRef(0)
  const aiShapeNameCounterRef = useRef(0)
  const isLoadingRef = useRef(false)
  const isSavingRef = useRef(false)
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const AI_MARKERS_LAYER = 'AI Markers'

  useEffect(() => { bookmarksRef.current = bookmarks }, [bookmarks])
  useEffect(() => { mapBoundsRef.current = mapBounds }, [mapBounds])

  // ── Resizable panels ──

  const [leftWidth, setLeftWidth] = useState(260)
  const [rightWidth, setRightWidth] = useState(380)

  const onResizeStart = useCallback(
    (side: 'left' | 'right') => (e: React.MouseEvent) => {
      e.preventDefault()
      const startX = e.clientX
      const startW = side === 'left' ? leftWidth : rightWidth

      document.body.classList.add('resizing')

      const onMove = (ev: MouseEvent) => {
        const delta = ev.clientX - startX
        if (side === 'left') {
          setLeftWidth(Math.max(180, Math.min(500, startW + delta)))
        } else {
          setRightWidth(Math.max(280, Math.min(600, startW - delta)))
        }
      }

      const onUp = () => {
        document.body.classList.remove('resizing')
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }

      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [leftWidth, rightWidth],
  )

  // ── Workspace ──

  // Auto-restore last workspace on startup
  useEffect(() => {
    window.electronAPI.getLastWorkspace().then((last) => {
      if (last) setWorkspacePath(last)
    }).catch(() => {})
  }, [])

  const handleSelectWorkspace = async (): Promise<void> => {
    const selected = await window.electronAPI.selectWorkspace()
    if (selected) {
      setWorkspacePath(selected)
      window.electronAPI.setLastWorkspace(selected).catch(() => {})
    }
  }

  // ── Layer management ──

  const addLayer = useCallback(
    async (name: string, filePath: string) => {
      if (layers.find((l) => l.filePath === filePath)) {
        setActiveLeftTab('layers')
        return
      }
      const content = await window.electronAPI.readFile(filePath)
      if (!content) return
      try {
        const raw = JSON.parse(content)
        const data =
          raw.type === 'FeatureCollection'
            ? raw
            : raw.type === 'Feature'
              ? { type: 'FeatureCollection', features: [raw] }
              : {
                  type: 'FeatureCollection',
                  features: [{ type: 'Feature', geometry: raw, properties: {} }],
                }

        const color = LAYER_COLORS[colorIndexRef.current % LAYER_COLORS.length]
        colorIndexRef.current++

        const layer: GeoJSONLayer = {
          id: `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          name,
          filePath,
          visible: true,
          data,
          color,
        }
        setLayers((prev) => [...prev, layer])
        setActiveLeftTab('layers')
      } catch (e) {
        console.error('Invalid GeoJSON:', e)
      }
    },
    [layers],
  )

  const removeLayer = useCallback((id: string) => {
    setLayers((prev) => prev.filter((l) => l.id !== id))
  }, [])

  const toggleLayer = useCallback((id: string) => {
    setLayers((prev) => prev.map((l) => (l.id === id ? { ...l, visible: !l.visible } : l)))
  }, [])

  const zoomToLayer = useCallback((id: string) => {
    const layer = layers.find((l) => l.id === id)
    if (!layer?.data) return
    try {
      const bbox = turf.bbox(layer.data) as [number, number, number, number]
      if (bbox.every((v) => isFinite(v))) {
        setMapActions((prev) => [
          ...prev,
          { type: 'fit_bounds', payload: { west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] } },
        ])
      }
    } catch { /* ignore invalid geometry */ }
  }, [layers])

  // Convert a non-GeoJSON vector file (shapefile/GPKG/KML/KMZ/GPX/CSV) to a
  // workspace-local .geojson via the backend, then load it as a layer. Requires
  // an open workspace (the backend writes the converted file inside it).
  const convertAndAddLayer = useCallback(
    async (entry: FileEntry) => {
      if (!workspacePath) {
        setConvertError('Open a workspace folder before importing this file type.')
        return
      }
      setConvertingFile(entry.name)
      setConvertError(null)
      try {
        const resp = await fetch('http://localhost:8765/api/files/convert', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: entry.path, workspace: workspacePath }),
        })
        const data = await resp.json()
        if (data.error) {
          setConvertError(`${entry.name}: ${data.error}`)
          return
        }
        if (data.path) {
          await addLayer(data.name || entry.name, data.path)
        }
      } catch {
        setConvertError(`Could not reach the backend to convert ${entry.name}.`)
      } finally {
        setConvertingFile(null)
      }
    },
    [workspacePath, addLayer],
  )

  const handleFileClick = useCallback(
    (entry: FileEntry) => {
      const lower = entry.name.toLowerCase()
      if (lower.endsWith('.geojson') || lower.endsWith('.json')) {
        addLayer(entry.name.replace(/\.(geojson|json)$/i, ''), entry.path)
      } else if (/\.(shp|gpkg|kml|kmz|gpx|csv)$/.test(lower)) {
        void convertAndAddLayer(entry)
      }
    },
    [addLayer, convertAndAddLayer],
  )

  // ── Admin boundary save ──

  const handlePreviewBoundary = useCallback((geom: BoundaryGeometry | null) => {
    if (geom) {
      const previewFC: FeatureCollection = {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', geometry: geom, properties: {} }],
      }
      setMapActions((prev) => [
        ...prev,
        {
          type: 'add_geojson',
          payload: {
            geojson: previewFC,
            name: '__boundary_preview__',
            color: '#f59e0b',
          },
        },
      ])
    } else {
      setMapActions((prev) => [
        ...prev,
        { type: 'remove_layer', payload: { layer_name: '__boundary_preview__' } },
      ])
    }
  }, [])

  const handleSaveByRegion = useCallback(async (displayName: string, boundaryGeom: BoundaryGeometry) => {
    if (!workspacePath || layers.length === 0) return
    const boundary: Feature<BoundaryGeometry> = { type: 'Feature', geometry: boundaryGeom, properties: {} }
    const allClipped: Feature[] = []
    for (const layer of layers) {
      for (const f of layer.data?.features || []) {
        const t = f.geometry?.type
        try {
          if (t === 'Polygon' || t === 'MultiPolygon') {
            const clipped = turf.intersect(
              turf.featureCollection([
                f as Feature<Polygon | MultiPolygon>,
                boundary as Feature<Polygon | MultiPolygon>,
              ]),
            )
            if (clipped) {
              allClipped.push({
                ...clipped,
                properties: { ...(f.properties || {}), source_layer: layer.name },
              })
            }
          } else if (t === 'Point') {
            if (
              turf.booleanPointInPolygon(
                f as Feature<import('geojson').Point>,
                boundary as Feature<Polygon | MultiPolygon>,
              )
            ) {
              allClipped.push({
                ...f,
                properties: { ...(f.properties || {}), source_layer: layer.name },
              })
            }
          } else if (t === 'MultiPoint') {
            const coords = (f.geometry as import('geojson').MultiPoint).coordinates
            const inside = coords.filter((c) =>
              turf.booleanPointInPolygon(turf.point(c), boundary as Feature<Polygon | MultiPolygon>),
            )
            if (inside.length) {
              allClipped.push({
                type: 'Feature',
                geometry: { type: 'MultiPoint', coordinates: inside },
                properties: { ...(f.properties || {}), source_layer: layer.name },
              })
            }
          } else if (t === 'LineString' || t === 'MultiLineString') {
            if (
              turf.booleanIntersects(
                f as Feature,
                boundary as Feature<Polygon | MultiPolygon>,
              )
            ) {
              allClipped.push({
                ...f,
                properties: { ...(f.properties || {}), source_layer: layer.name },
              })
            }
          }
        } catch {
          /* skip invalid geometry */
        }
      }
    }
    const safeName = displayName.replace(/[^a-z0-9-_]/gi, '_').slice(0, 40) || 'region'
    const filePath = `${workspacePath}/${safeName}.geojson`
    await window.electronAPI.writeFile(
      filePath,
      JSON.stringify({ type: 'FeatureCollection', features: allClipped }, null, 2),
    )
    addLayer(safeName, filePath)
    setActiveLeftTab('layers')
    setMapActions((prev) => [
      ...prev,
      { type: 'remove_layer', payload: { layer_name: '__boundary_preview__' } },
    ])
  }, [workspacePath, layers, addLayer])

  const handleBookmarkGoTo = useCallback((b: MapBookmark) => {
    setMapActions((prev) => [
      ...prev,
      {
        type: 'fit_bounds',
        payload: { south: b.south, west: b.west, north: b.north, east: b.east },
      },
    ])
  }, [])

  const handleBookmarkSaveCurrent = useCallback(
    (name: string) => {
      const bounds = mapBoundsRef.current
      if (!bounds) return
      setBookmarks((prev) => [
        ...prev,
        {
          id: genId(),
          name,
          ...bounds,
          zoom: mapViewState.zoom,
        },
      ])
      setActiveLeftTab('bookmarks')
    },
    [mapViewState.zoom],
  )

  const handleExportMapPng = useCallback(() => {
    const canvas = mapViewRef.current?.getCanvas()
    if (!canvas) return
    canvas.toBlob((blob) => {
      if (!blob) return
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `map-${Date.now()}.png`
      a.click()
      URL.revokeObjectURL(a.href)
    })
  }, [])

  const handleExportPdf = useCallback(async () => {
    const canvas = mapViewRef.current?.getCanvas()
    if (!canvas) return
    const { jsPDF } = await import('jspdf')
    const pdf = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' })
    const img = canvas.toDataURL('image/png')

    // A4 landscape ~842 × 595pt. Fit the canvas (in DPR-aware logical
    // pixels) into the page below the title, preserving aspect ratio.
    const pageW = pdf.internal.pageSize.getWidth()
    const pageH = pdf.internal.pageSize.getHeight()
    const margin = 40
    const titleSpace = 30
    const maxW = pageW - margin * 2
    const maxH = pageH - margin - titleSpace - margin
    const dpr = window.devicePixelRatio || 1
    const logicalW = canvas.width / dpr
    const logicalH = canvas.height / dpr
    const aspect = logicalH > 0 ? logicalW / logicalH : maxW / maxH
    let drawW = maxW
    let drawH = drawW / aspect
    if (drawH > maxH) {
      drawH = maxH
      drawW = drawH * aspect
    }
    const drawX = (pageW - drawW) / 2
    const drawY = margin + titleSpace

    pdf.setFontSize(14)
    pdf.text('Map export — Cursor for Urban Planners', margin, margin + 18)
    pdf.addImage(img, 'PNG', drawX, drawY, drawW, drawH)

    const footer = `Viewport export — ${new Date().toISOString()}`
    pdf.setFontSize(9)
    pdf.text(footer, margin, pageH - 18)
    pdf.save(`map-report-${Date.now()}.pdf`)
  }, [])

  const handleSavePngToArtifact = useCallback(async (title: string) => {
    const canvas = mapViewRef.current?.getCanvas()
    if (!canvas) return
    canvas.toBlob(async (blob) => {
      if (!blob) return
      const form = new FormData()
      form.append('title', title)
      form.append('artifact_type', 'sketch')
      form.append('format', 'image')
      form.append('content', '')
      form.append('file', blob, `${title.replace(/[^a-z0-9-_]/gi, '_')}.png`)
      try {
        await fetch('http://localhost:8765/api/artifacts/upload', { method: 'POST', body: form })
        setArtifactsRevision((n) => n + 1)
      } catch {
        /* backend unavailable */
      }
    })
  }, [])

  const handleSavePdfToArtifact = useCallback(async (title: string) => {
    const canvas = mapViewRef.current?.getCanvas()
    if (!canvas) return
    const { jsPDF } = await import('jspdf')
    const pdf = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' })
    const img = canvas.toDataURL('image/png')
    const pageW = pdf.internal.pageSize.getWidth()
    const pageH = pdf.internal.pageSize.getHeight()
    const margin = 40
    const titleSpace = 30
    const maxW = pageW - margin * 2
    const maxH = pageH - margin - titleSpace - margin
    const dpr = window.devicePixelRatio || 1
    const logicalW = canvas.width / dpr
    const logicalH = canvas.height / dpr
    const aspect = logicalH > 0 ? logicalW / logicalH : maxW / maxH
    let drawW = maxW
    let drawH = drawW / aspect
    if (drawH > maxH) { drawH = maxH; drawW = drawH * aspect }
    const drawX = (pageW - drawW) / 2
    const drawY = margin + titleSpace
    pdf.setFontSize(14)
    pdf.text(title, margin, margin + 18)
    pdf.addImage(img, 'PNG', drawX, drawY, drawW, drawH)
    const footer = `Viewport export — ${new Date().toISOString()}`
    pdf.setFontSize(9)
    pdf.text(footer, margin, pageH - 18)
    const pdfBytes = pdf.output('arraybuffer')
    const blob = new Blob([pdfBytes], { type: 'application/pdf' })
    const form = new FormData()
    form.append('title', title)
    form.append('artifact_type', 'sketch')
    form.append('format', 'image')
    form.append('content', '')
    form.append('file', blob, `${title.replace(/[^a-z0-9-_]/gi, '_')}.pdf`)
    try {
      await fetch('http://localhost:8765/api/artifacts/upload', { method: 'POST', body: form })
      setArtifactsRevision((n) => n + 1)
    } catch {
      /* backend unavailable */
    }
  }, [])

  const suggestExportTitle = useCallback((): string => {
    const topLayer = layers.length > 0 ? layers[layers.length - 1].name : null
    const date = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
    return topLayer ? `${topLayer} — ${date}` : `Map export — ${date}`
  }, [layers])

  const handleExportLayerFile = useCallback((layerId: string) => {
    const layer = layers.find((l) => l.id === layerId)
    if (!layer?.data) return
    const blob = new Blob([JSON.stringify(layer.data, null, 2)], { type: 'application/geo+json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${layer.name.replace(/[^a-z0-9-_]/gi, '_') || 'layer'}.geojson`
    a.click()
    URL.revokeObjectURL(a.href)
  }, [layers])

  // ── Shared helper: upsert a named GeoJSON layer ──

  const clipLayersToBboxAndSave = useCallback(
    async (
      outputBaseName: string,
      bboxExplicit?: { south: number; west: number; north: number; east: number },
    ) => {
      const b =
        bboxExplicit?.south != null
          ? bboxExplicit
          : mapBoundsRef.current
      if (!workspacePath || !b || !layers.length) return
      const bbox: [number, number, number, number] = [b.west, b.south, b.east, b.north]
      const allFeatures: Feature[] = []
      for (const layer of layers) {
        for (const f of layer.data?.features || []) {
          try {
            const clipped = turf.bboxClip(f as Feature<Polygon | MultiPolygon>, bbox)
            if (!clipped?.geometry) continue
            allFeatures.push({
              type: 'Feature',
              geometry: clipped.geometry,
              properties: { ...(f.properties || {}), source_layer: layer.name },
            })
          } catch {
            /* skip */
          }
        }
      }
      const base = (outputBaseName || 'clipped').replace(/[^a-z0-9-_]/gi, '_') || 'clipped'
      const path = `${workspacePath}/${base}.geojson`
      await window.electronAPI.writeFile(
        path,
        JSON.stringify({ type: 'FeatureCollection', features: allFeatures }, null, 2),
      )
      addLayer(base, path)
      setActiveLeftTab('layers')
    },
    [layers, workspacePath, addLayer],
  )

  const upsertLayer = useCallback((layerName: string, data: FeatureCollection, color?: string) => {
    const layerColor = color || LAYER_COLORS[colorIndexRef.current % LAYER_COLORS.length]
    colorIndexRef.current++
    setLayers((prev) => {
      const newLayer = {
        id: `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        name: layerName,
        filePath: '',
        visible: true,
        data,
        color: layerColor,
      }
      const existingIdx = prev.findIndex(
        (l) => l.name.toLowerCase() === layerName.toLowerCase(),
      )
      if (existingIdx >= 0) {
        const updated = [...prev]
        updated[existingIdx] = { ...newLayer, id: prev[existingIdx].id }
        return updated
      }
      return [...prev, newLayer]
    })
    setActiveLeftTab('layers')
  }, [])

  // Append-merge AI-placed markers into the canonical "AI Markers" layer.
  // We intercept add_marker / add_markers in handleMapAction so the pins
  // live in React state (and project.json), not in a MapView ref that
  // disappears on reload.
  const appendMarkersToLayer = useCallback(
    (markers: Array<{ lat: number; lng: number; label?: string; color?: string }>) => {
      if (!markers.length) return
      const newFeatures: Feature[] = markers
        .filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lng))
        .map((m) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [m.lng, m.lat] },
          properties: {
            label: m.label || '',
            ...(m.color ? { fillColor: m.color, strokeColor: m.color } : {}),
            source: 'ai_marker',
          },
        }))
      if (!newFeatures.length) return
      setLayers((prev) => {
        const idx = prev.findIndex(
          (l) => l.name.toLowerCase() === AI_MARKERS_LAYER.toLowerCase(),
        )
        if (idx >= 0) {
          const merged = {
            ...prev[idx],
            visible: true,
            data: {
              type: 'FeatureCollection',
              features: [...(prev[idx].data?.features || []), ...newFeatures],
            } as FeatureCollection,
          }
          const next = [...prev]
          next[idx] = merged
          return next
        }
        const layerColor = LAYER_COLORS[colorIndexRef.current % LAYER_COLORS.length]
        colorIndexRef.current++
        return [
          ...prev,
          {
            id: `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            name: AI_MARKERS_LAYER,
            filePath: '',
            visible: true,
            data: { type: 'FeatureCollection', features: newFeatures } as FeatureCollection,
            color: layerColor,
          },
        ]
      })
      setActiveLeftTab('layers')
    },
    [],
  )

  const handleLayerStyleChange = useCallback(
    (
      layerName: string,
      style: { fillColor?: string; lineColor?: string; opacity?: number },
    ) => {
      setLayers((prev) =>
        prev.map((l) =>
          l.name.toLowerCase() === layerName.toLowerCase()
            ? {
                ...l,
                ...(style.fillColor !== undefined ? { fillColor: style.fillColor } : {}),
                ...(style.lineColor !== undefined ? { lineColor: style.lineColor } : {}),
                ...(style.opacity !== undefined ? { opacity: style.opacity } : {}),
              }
            : l,
        ),
      )
    },
    [],
  )

  // Build a LayerStyleSpec from a `style_layer` action payload, reading the
  // layer's feature values to compute category palettes / numeric breaks.
  // Shared by the AI action path and (indirectly) the manual SymbologyPanel.
  const buildStyleSpec = useCallback(
    (
      layer: GeoJSONLayer,
      p: Extract<MapAction, { type: 'style_layer' }>['payload'],
    ): LayerStyleSpec => {
      const feats = layer.data?.features || []
      // Carry forward existing labels unless the payload changes them.
      const prevLabel = layer.styleSpec?.label
      const spec: LayerStyleSpec = {
        mode: p.mode,
        opacity: p.opacity ?? layer.styleSpec?.opacity,
        label: prevLabel,
      }

      if (p.mode === 'categorized' && p.property) {
        const values = feats.map((f) => String(f.properties?.[p.property!] ?? ''))
        spec.property = p.property
        spec.categories = p.categories?.length
          ? p.categories
          : buildCategories(values, p.property, p.ramp || 'category')
        spec.otherColor = layer.color
        spec.rampName = p.ramp || 'category'
      } else if (p.mode === 'graduated' && p.property) {
        const nums = feats
          .map((f) => Number(f.properties?.[p.property!]))
          .filter((n) => Number.isFinite(n))
        const classes = Math.max(2, Math.min(p.classes ?? 5, 9))
        const method = p.classification || 'quantile'
        const breaks = computeBreaks(nums, classes, method)
        const rampName = p.ramp || DEFAULT_RAMP
        spec.property = p.property
        spec.breaks = breaks
        // rampColors length must equal breaks.length + 1 (one color per bucket).
        spec.rampColors = rampColorsForClasses(rampName, breaks.length + 1)
        spec.classification = method
        spec.rampName = rampName
      }

      // Label changes (independent of color mode).
      if (p.label_property !== undefined || p.label_enabled !== undefined ||
          p.label_size !== undefined || p.label_color !== undefined) {
        const property = p.label_property ?? prevLabel?.property ?? ''
        spec.label = {
          enabled: p.label_enabled ?? (p.label_property ? true : prevLabel?.enabled ?? false),
          property,
          size: p.label_size ?? prevLabel?.size,
          color: p.label_color ?? prevLabel?.color,
          haloColor: prevLabel?.haloColor,
        }
      }

      return spec
    },
    [],
  )

  // Direct UI path: SymbologyPanel writes a fully-formed styleSpec onto a layer.
  const handleSymbologyChange = useCallback((layerId: string, styleSpec: LayerStyleSpec) => {
    setLayers((prev) => prev.map((l) => (l.id === layerId ? { ...l, styleSpec } : l)))
  }, [])

  const stylingLayer = useMemo(
    () => layers.find((l) => l.id === stylingLayerId) ?? null,
    [layers, stylingLayerId],
  )

  // ── Map action handler (intercepts layer ops, queues the rest) ──

  const handleMapAction = useCallback((action: MapAction) => {
    if (action.type === 'style_layer') {
      const p = action.payload
      setLayers((prev) =>
        prev.map((l) =>
          l.name.toLowerCase() === p.layer_name?.toLowerCase()
            ? { ...l, styleSpec: buildStyleSpec(l, p) }
            : l,
        ),
      )
      setActiveLeftTab('layers')
      return
    }
    if (action.type === 'save_bookmark') {
      const { name, south, west, north, east, zoom } = action.payload
      const bounds =
        south != null && west != null && north != null && east != null
          ? { south, west, north, east }
          : mapBoundsRef.current
      if (!name || !bounds) return
      setBookmarks((prev) => [
        ...prev,
        {
          id: genId(),
          name: String(name),
          south: bounds.south,
          west: bounds.west,
          north: bounds.north,
          east: bounds.east,
          zoom: zoom != null ? Number(zoom) : mapViewState.zoom,
        },
      ])
      setActiveLeftTab('bookmarks')
      return
    }
    if (action.type === 'go_to_bookmark') {
      const raw = String(action.payload.name || '').toLowerCase()
      const bm = bookmarksRef.current.find(
        (x) =>
          x.name.toLowerCase().includes(raw) || raw.includes(x.name.toLowerCase()),
      )
      if (bm) {
        setMapActions((prev) => [
          ...prev,
          {
            type: 'fit_bounds',
            payload: {
              south: bm.south,
              west: bm.west,
              north: bm.north,
              east: bm.east,
            },
          },
        ])
      }
      return
    }
    if (action.type === 'export_region_clip') {
      const { output_base_name, south, west, north, east } = action.payload
      const explicit =
        south != null && west != null && north != null && east != null
          ? { south: Number(south), west: Number(west), north: Number(north), east: Number(east) }
          : undefined
      void clipLayersToBboxAndSave(String(output_base_name || 'clipped'), explicit)
      return
    }
    if (action.type === 'add_geojson') {
      const { geojson, name, color } = action.payload
      const geometryTypes = ['Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon','GeometryCollection']
      const data: FeatureCollection =
        geojson && 'type' in geojson && geojson.type === 'FeatureCollection'
          ? (geojson as FeatureCollection)
          : geojson && 'type' in geojson && geojson.type === 'Feature'
            ? { type: 'FeatureCollection', features: [geojson as Feature] }
            : geojson && 'type' in geojson && geometryTypes.includes(geojson.type as string)
              ? { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: geojson as Geometry, properties: {} }] }
              : { type: 'FeatureCollection', features: [] }
      upsertLayer(name || 'AI Layer', data, color)
      return
    }
    if (action.type === 'toggle_layer') {
      setLayers((prev) =>
        prev.map((l) =>
          l.name.toLowerCase() === action.payload.layer_name?.toLowerCase()
            ? { ...l, visible: !!action.payload.visible }
            : l,
        ),
      )
      return
    }
    if (action.type === 'remove_layer') {
      setLayers((prev) =>
        prev.filter(
          (l) => l.name.toLowerCase() !== action.payload.layer_name?.toLowerCase(),
        ),
      )
      return
    }
    if (action.type === 'refresh_artifacts') {
      setArtifactsRevision((n) => n + 1)
      return
    }
    // AI-placed pins: merge into a single "AI Markers" Point layer so they
    // appear in mapContext, persist to project.json, and survive reload.
    if (action.type === 'add_marker') {
      appendMarkersToLayer([action.payload])
      return
    }
    if (action.type === 'add_markers') {
      const list = Array.isArray(action.payload?.markers) ? action.payload.markers : []
      appendMarkersToLayer(list)
      return
    }
    if (action.type === 'clear_markers') {
      setLayers((prev) =>
        prev.filter((l) => l.name.toLowerCase() !== AI_MARKERS_LAYER.toLowerCase()),
      )
      return
    }
    // Promote AI-drawn shapes to real layers so they appear in mapContext on
    // the next turn. Without this they live only in the MapView ref and the
    // assistant can't see them again.
    if (action.type === 'draw_line') {
      const { coordinates, label, color } = action.payload
      if (Array.isArray(coordinates) && coordinates.length >= 2) {
        aiShapeNameCounterRef.current += 1
        const name = label || `AI Line ${aiShapeNameCounterRef.current}`
        upsertLayer(
          name,
          {
            type: 'FeatureCollection',
            features: [{
              type: 'Feature',
              geometry: { type: 'LineString', coordinates },
              properties: { label: label || '', source: 'ai_draw' },
            }],
          },
          color,
        )
      }
      return
    }
    if (action.type === 'draw_polygon') {
      const { coordinates, label, color } = action.payload
      const raw = Array.isArray(coordinates) ? coordinates : []
      if (raw.length >= 3) {
        const ring =
          raw[0][0] !== raw[raw.length - 1][0] || raw[0][1] !== raw[raw.length - 1][1]
            ? [...raw, raw[0]]
            : raw
        aiShapeNameCounterRef.current += 1
        const name = label || `AI Polygon ${aiShapeNameCounterRef.current}`
        upsertLayer(
          name,
          {
            type: 'FeatureCollection',
            features: [{
              type: 'Feature',
              geometry: { type: 'Polygon', coordinates: [ring] },
              properties: { label: label || '', source: 'ai_draw' },
            }],
          },
          color,
        )
      }
      return
    }
    if (action.type === 'draw_circle') {
      const { center_lng, center_lat, radius_km, label, color } = action.payload
      if (radius_km > 0) {
        const circle = turf.circle([center_lng, center_lat], radius_km, {
          units: 'kilometers',
          steps: 64,
        })
        circle.properties = {
          label: label || '',
          source: 'ai_draw',
          center_lng,
          center_lat,
          radius_km,
        }
        aiShapeNameCounterRef.current += 1
        const name = label || `AI Circle ${aiShapeNameCounterRef.current}`
        upsertLayer(
          name,
          { type: 'FeatureCollection', features: [circle] },
          color,
        )
      }
      return
    }
    setMapActions((prev) => [...prev, action])
  }, [upsertLayer, clipLayersToBboxAndSave, appendMarkersToLayer, mapViewState.zoom, buildStyleSpec])

  // ── Right-click map actions ──

  const handleRightClickAddMarker = useCallback(
    (lng: number, lat: number) => {
      // Place immediately with a coordinate label, then upgrade to the
      // reverse-geocoded address when it resolves. Never block the pin.
      appendMarkersToLayer([{ lng, lat, label: `${lat.toFixed(5)}, ${lng.toFixed(5)}` }])
      fetch(`http://localhost:8765/api/geocode/reverse?lat=${lat}&lng=${lng}`)
        .then((r) => r.json())
        .then((d: { display_name?: string | null }) => {
          if (!d?.display_name) return
          setLayers((prev) =>
            prev.map((l) => {
              if (l.name.toLowerCase() !== AI_MARKERS_LAYER.toLowerCase()) return l
              const features = [...(l.data?.features || [])]
              // Update the most-recently-added point matching these coords.
              for (let i = features.length - 1; i >= 0; i--) {
                const g = features[i].geometry
                if (g?.type === 'Point' && g.coordinates[0] === lng && g.coordinates[1] === lat) {
                  features[i] = {
                    ...features[i],
                    properties: { ...features[i].properties, label: d.display_name },
                  }
                  break
                }
              }
              return { ...l, data: { type: 'FeatureCollection', features } as FeatureCollection }
            }),
          )
        })
        .catch(() => { /* keep coordinate label */ })
    },
    [appendMarkersToLayer],
  )

  const handleRightClickStreetView = useCallback((lng: number, lat: number) => {
    setStreetViewTarget({ lng, lat })
  }, [])

  const handleRightClickAskChat = useCallback(
    (lng: number, lat: number) => {
      setActiveRightTab('chat')
      const text =
        `Tell me everything you can about this location (${lat.toFixed(5)}, ${lng.toFixed(5)}): ` +
        `the address/neighborhood, nearby amenities, demographics, weather, and any notable features. Use your tools.`
      setInjectedMessage((prev) => ({ text, nonce: (prev?.nonce || 0) + 1 }))
    },
    [],
  )

  // ── Map context for AI ──

  const mapContext: MapContext = useMemo(
    () => ({
      center: mapViewState.center,
      zoom: mapViewState.zoom,
      bounds: mapBounds
        ? { west: mapBounds.west, south: mapBounds.south, east: mapBounds.east, north: mapBounds.north }
        : undefined,
      bookmarks: bookmarks.map((b) => ({
        name: b.name, south: b.south, west: b.west, north: b.north, east: b.east, zoom: b.zoom,
      })),
      layers: layers.map((l) => {
        const features: Feature[] = l.data?.features || []
        const featureCount = features.length
        const geometryTypes = [
          ...new Set(
            features.map((f) => f.geometry?.type).filter((t): t is NonNullable<typeof t> => Boolean(t)),
          ),
        ]
        const properties = [
          ...new Set(
            features.flatMap((f) => Object.keys(f.properties || {})),
          ),
        ].slice(0, 20)

        // Include actual coordinates for small layers (≤5 features) so the
        // LLM can compute centroids, buffers, intersections, etc.
        let geometry_data: LayerGeometryData | undefined = undefined
        const totalCoords = features.reduce((sum: number, f) => {
          const g = f.geometry
          if (!g || !('coordinates' in g)) return sum
          const c = g.coordinates
          if (g.type === 'Point') return sum + 1
          if (g.type === 'LineString' && Array.isArray(c)) return sum + c.length
          if (g.type === 'Polygon' && Array.isArray(c)) return sum + ((c[0] as unknown[])?.length || 0)
          if (g.type === 'MultiPolygon' && Array.isArray(c))
            return sum + (c as unknown[][][]).reduce((s, p) => s + (p[0]?.length || 0), 0)
          return sum + 10
        }, 0)

        if (featureCount <= 5 && totalCoords <= 200) {
          geometry_data = features.map((f) => ({
            type: f.geometry?.type,
            coordinates: f.geometry && 'coordinates' in f.geometry ? f.geometry.coordinates : undefined,
          }))
        } else {
          try {
            const bbox = turf.bbox(l.data) as [number, number, number, number]
            if (bbox.every((v) => isFinite(v))) {
              geometry_data = { bbox }
            }
          } catch { /* ignore */ }
        }

        const s = l.styleSpec
        const style = s
          ? {
              mode: s.mode,
              property: s.property,
              categoryCount: s.categories?.length,
              classes: s.breaks ? s.breaks.length + 1 : undefined,
              ramp: s.rampName,
              labels: (s.label?.enabled
                ? { property: s.label.property }
                : false) as false | { property: string },
            }
          : { mode: 'simple' as const, labels: false as const }

        return {
          name: l.name,
          featureCount,
          geometryTypes,
          properties,
          visible: l.visible,
          ...(geometry_data ? { geometry_data } : {}),
          style,
        }
      }),
      basemap,
    }),
    [mapViewState, mapBounds, bookmarks, layers, basemap],
  )

  // ── Conversation helpers ──

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeConversationId) ?? null,
    [conversations, activeConversationId],
  )

  const handleCreateConversation = useCallback(() => {
    const id = genId()
    const conv: Conversation = { id, title: 'New chat', messages: [], createdAt: Date.now() }
    setConversations((prev) => [conv, ...prev])
    setActiveConversationId(id)
  }, [])

  const handleSelectConversation = useCallback((id: string) => {
    setActiveConversationId(id)
  }, [])

  const handleDeleteConversation = useCallback(
    (id: string) => {
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeConversationId === id) {
        setActiveConversationId(null)
      }
    },
    [activeConversationId],
  )

  const handleConversationMessagesChange = useCallback(
    (messages: import('./types').ChatMessage[]) => {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== activeConversationId) return c
          const title =
            c.title === 'New chat' && messages.length > 0
              ? (messages.find((m) => m.role === 'user')?.content.slice(0, 60) || 'New chat')
              : c.title
          return { ...c, messages, title }
        }),
      )
    },
    [activeConversationId],
  )

  // ── Project persistence ──

  const saveProject = useCallback(
    async (force = false) => {
      if (!workspacePath) return
      if (!force && isLoadingRef.current) return
      isSavingRef.current = true
      try {
        let layersSnapshot = layers
        const withPaths: GeoJSONLayer[] = []
        let materializedAny = false
        for (const l of layers) {
          if (l.filePath?.trim()) {
            withPaths.push(l)
            continue
          }
          const fp = `${workspacePath}/.cursor-urban/layers/${l.id}.geojson`
          const ok = await window.electronAPI.writeFile(fp, JSON.stringify(l.data, null, 2))
          if (!ok) {
            console.error('Failed to persist layer:', l.name)
            withPaths.push(l)
            continue
          }
          withPaths.push({ ...l, filePath: fp })
          materializedAny = true
        }
        if (materializedAny) {
          layersSnapshot = withPaths
          setLayers(withPaths)
        }

        // Store paths relative to the workspace so the project survives a
        // workspace-folder move. loadProject re-resolves against the
        // current workspacePath.
        const wsPrefix = workspacePath.endsWith('/') ? workspacePath : `${workspacePath}/`
        const toRelative = (fp: string): string =>
          fp.startsWith(wsPrefix) ? fp.slice(wsPrefix.length) : fp

        const projectData: ProjectData = {
          mapState: mapViewState,
          layers: layersSnapshot.map((l) => ({
            name: l.name,
            filePath: toRelative(l.filePath),
            visible: l.visible,
            color: l.color,
            ...(l.fillColor !== undefined ? { fillColor: l.fillColor } : {}),
            ...(l.lineColor !== undefined ? { lineColor: l.lineColor } : {}),
            ...(l.opacity !== undefined ? { opacity: l.opacity } : {}),
            ...(l.styleSpec !== undefined ? { styleSpec: l.styleSpec } : {}),
          })),
          conversations,
          activeConversationId,
          basemap,
          bookmarks,
        }
        const wrote = await window.electronAPI.writeFile(
          `${workspacePath}/project.json`,
          JSON.stringify(projectData, null, 2),
        )
        if (!wrote) console.error('Failed to save project.json (check workspace permissions)')
      } finally {
        isSavingRef.current = false
      }
    },
    [workspacePath, mapViewState, layers, conversations, activeConversationId, basemap, bookmarks],
  )

  saveProjectRef.current = saveProject

  const loadProject = useCallback(async () => {
    if (!workspacePath) return
    isLoadingRef.current = true
    setBookmarks([])
    try {
      const content = await window.electronAPI.readFile(`${workspacePath}/project.json`)
      if (!content) {
        isLoadingRef.current = false
        return
      }
      const data: ProjectData = JSON.parse(content)
      if (data.mapState) {
        setMapViewState(data.mapState)
        setMapActions([{ type: 'set_view', payload: data.mapState }])
      }
      if (data.basemap) setBasemap(data.basemap)
      if (data.bookmarks && data.bookmarks.length > 0) setBookmarks(data.bookmarks)

      if (data.conversations && data.conversations.length > 0) {
        setConversations(data.conversations)
        setActiveConversationId(data.activeConversationId ?? data.conversations[0].id)
      } else if (data.chatHistory && data.chatHistory.length > 0) {
        const migrated: Conversation = {
          id: genId(),
          title: data.chatHistory.find((m) => m.role === 'user')?.content.slice(0, 60) || 'Imported chat',
          messages: data.chatHistory,
          createdAt: data.chatHistory[0]?.timestamp || Date.now(),
        }
        setConversations([migrated])
        setActiveConversationId(migrated.id)
      }

      if (data.layers) {
        const loadedLayers: GeoJSONLayer[] = []
        const wsPrefix = workspacePath.endsWith('/') ? workspacePath : `${workspacePath}/`
        for (const info of data.layers) {
          if (!info.filePath?.trim()) {
            console.warn('Skipping layer with no file path (re-add from chat or disk):', info.name)
            continue
          }
          // Resolve relative paths against the current workspace so the
          // project survives a workspace-folder move. Absolute paths from
          // older project.json files keep working.
          const resolved = info.filePath.startsWith('/')
            ? info.filePath
            : `${wsPrefix}${info.filePath}`
          const fileContent = await window.electronAPI.readFile(resolved)
          if (!fileContent) {
            console.warn('Layer file missing:', info.name, resolved)
            continue
          }
          try {
            const raw = JSON.parse(fileContent)
            const geojson =
              raw.type === 'FeatureCollection'
                ? raw
                : raw.type === 'Feature'
                  ? { type: 'FeatureCollection', features: [raw] }
                  : {
                      type: 'FeatureCollection',
                      features: [{ type: 'Feature', geometry: raw, properties: {} }],
                    }
            loadedLayers.push({
              id: `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
              name: info.name,
              filePath: resolved,
              visible: info.visible,
              data: geojson,
              color: info.color,
              ...(info.fillColor !== undefined ? { fillColor: info.fillColor } : {}),
              ...(info.lineColor !== undefined ? { lineColor: info.lineColor } : {}),
              ...(info.opacity !== undefined ? { opacity: info.opacity } : {}),
              ...(info.styleSpec !== undefined ? { styleSpec: info.styleSpec } : {}),
            })
          } catch {
            /* skip invalid files */
          }
        }
        setLayers(loadedLayers)
        colorIndexRef.current = loadedLayers.length
      }
    } catch (e) {
      console.error('Failed to load project:', e)
    }
    setTimeout(() => {
      isLoadingRef.current = false
    }, 500)
  }, [workspacePath])

  useEffect(() => {
    if (workspacePath) loadProject()
  }, [workspacePath, loadProject])

  useEffect(() => {
    if (!workspacePath || isLoadingRef.current || isSavingRef.current) return
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    saveTimeoutRef.current = setTimeout(() => void saveProject(), 800)
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    }
  }, [workspacePath, mapViewState, layers, conversations, activeConversationId, basemap, bookmarks, saveProject])

  useEffect(() => {
    window.electronAPI.onAppBeforeQuit(async () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
        saveTimeoutRef.current = null
      }
      await saveProjectRef.current(true)
    })
  }, [])

  const workspaceLabel = workspacePath ? workspacePath.split('/').pop() : 'Open Workspace'

  return (
    <div className="app">
      <header className="titlebar">
        <div className="titlebar-drag" />
        <span className="titlebar-text">Cursor for Urban Planners</span>
        <div className="mode-switcher">
          <button
            className={`mode-btn ${appMode === 'map' ? 'active' : ''}`}
            onClick={() => setAppMode('map')}
          >
            Map
          </button>
          <button
            className={`mode-btn ${appMode === 'document' ? 'active' : ''}`}
            onClick={() => { setAppMode('document'); setDocumentImage(null) }}
          >
            Document
          </button>
        </div>
        {appMode === 'map' && (
          <button className="workspace-btn" onClick={handleSelectWorkspace}>
            {workspaceLabel}
          </button>
        )}
      </header>

      <div className="layout">
        {/* Left panel — map mode only */}
        {appMode === 'document' ? null : (
        <aside className="panel left-panel" style={{ width: leftWidth }}>
          <div className="tab-bar tab-bar-scroll">
            <button
              className={`tab ${activeLeftTab === 'files' ? 'active' : ''}`}
              onClick={() => setActiveLeftTab('files')}
            >
              Files
            </button>
            <button
              className={`tab ${activeLeftTab === 'layers' ? 'active' : ''}`}
              onClick={() => setActiveLeftTab('layers')}
            >
              Layers
              {layers.length > 0 && <span className="tab-badge">{layers.length}</span>}
            </button>
            <button
              className={`tab ${activeLeftTab === 'bookmarks' ? 'active' : ''}`}
              onClick={() => setActiveLeftTab('bookmarks')}
            >
              Marks
              {bookmarks.length > 0 && <span className="tab-badge">{bookmarks.length}</span>}
            </button>
            <button
              className={`tab ${activeLeftTab === 'export' ? 'active' : ''}`}
              onClick={() => setActiveLeftTab('export')}
            >
              Export
            </button>
            <button
              className={`tab ${activeLeftTab === 'zoning' ? 'active' : ''}`}
              onClick={() => setActiveLeftTab('zoning')}
            >
              Zones
            </button>
          </div>
          {activeLeftTab === 'files' && (
            <>
              {convertingFile && (
                <div className="import-status">Importing {convertingFile}…</div>
              )}
              {convertError && (
                <div className="import-status import-error" onClick={() => setConvertError(null)}>
                  {convertError}
                </div>
              )}
              <FileTree workspacePath={workspacePath} onFileClick={handleFileClick} />
            </>
          )}
          {activeLeftTab === 'layers' && (
            <>
              <LayerPanel
                layers={layers}
                onToggle={toggleLayer}
                onRemove={removeLayer}
                onZoomTo={zoomToLayer}
                onStyle={(id) => setStylingLayerId((cur) => (cur === id ? null : id))}
                activeStyleId={stylingLayerId}
              />
              {stylingLayer && (
                <SymbologyPanel
                  layer={stylingLayer}
                  onChange={handleSymbologyChange}
                  onClose={() => setStylingLayerId(null)}
                />
              )}
            </>
          )}
          {activeLeftTab === 'bookmarks' && (
            <BookmarkPanel
              bookmarks={bookmarks}
              onGoTo={handleBookmarkGoTo}
              onRemove={(id) => setBookmarks((prev) => prev.filter((b) => b.id !== id))}
              onSaveCurrent={handleBookmarkSaveCurrent}
            />
          )}
          {activeLeftTab === 'export' && (
            <ExportPanel
              layers={layers}
              workspacePath={workspacePath}
              onExportMapPng={handleExportMapPng}
              onExportLayer={handleExportLayerFile}
              onExportPdf={handleExportPdf}
              onExportClippedRegion={(name) => void clipLayersToBboxAndSave(name)}
              onPreviewBoundary={handlePreviewBoundary}
              onSaveByRegion={handleSaveByRegion}
              onSavePngToArtifact={handleSavePngToArtifact}
              onSavePdfToArtifact={handleSavePdfToArtifact}
              onSuggestExportTitle={suggestExportTitle}
            />
          )}
          {activeLeftTab === 'zoning' && <ZoningPanel />}
        </aside>
        )}

        {/* Left resize handle — map mode only */}
        {appMode === 'map' && <div className="resize-handle" onMouseDown={onResizeStart('left')} />}

        {/* Center */}
        <main className="center-panel">
          {appMode === 'map' ? (
            <div className="map-stack">
              {!workspacePath && (
                <div className="workspace-hint-banner">
                  Open a workspace folder (title bar) to save the map and export. Layers from chat still
                  appear, but they will not persist until a folder is open.
                </div>
              )}
              <ErrorBoundary label="Map">
                <MapView
                  ref={mapViewRef}
                  layers={layers}
                  basemap={basemap}
                  initialState={mapViewState}
                  mapActions={mapActions}
                  onMapMove={setMapViewState}
                  onBoundsChange={setMapBounds}
                  onBasemapChange={setBasemap}
                  onActionsProcessed={() => setMapActions([])}
                  onLayerStyleChange={handleLayerStyleChange}
                  onAddMarker={handleRightClickAddMarker}
                  onOpenStreetView={handleRightClickStreetView}
                  onAskChat={handleRightClickAskChat}
                />
              </ErrorBoundary>
              <Legend layers={layers} />
            </div>
          ) : (
            <ErrorBoundary label="Document">
              <DocumentView onImageChange={setDocumentImage} />
            </ErrorBoundary>
          )}
        </main>

        {/* Right resize handle */}
        <div className="resize-handle" onMouseDown={onResizeStart('right')} />

        {/* Right panel */}
        <aside className="panel right-panel" style={{ width: rightWidth }}>
          <div className="tab-bar">
            <button
              className={`tab ${activeRightTab === 'chat' ? 'active' : ''}`}
              onClick={() => setActiveRightTab('chat')}
            >
              Chat
            </button>
            {appMode === 'map' && (
              <button
                className={`tab ${activeRightTab === 'artifacts' ? 'active' : ''}`}
                onClick={() => setActiveRightTab('artifacts')}
              >
                Artifacts
              </button>
            )}
          </div>
          {activeRightTab === 'chat' || appMode === 'document' ? (
            <ErrorBoundary label="Chat">
              <ChatPanel
                conversations={conversations}
                activeConversation={activeConversation}
                onCreateConversation={handleCreateConversation}
                onSelectConversation={handleSelectConversation}
                onDeleteConversation={handleDeleteConversation}
                onMessagesChange={handleConversationMessagesChange}
                mapContext={mapContext}
                onMapAction={handleMapAction}
                documentImage={appMode === 'document' ? documentImage : null}
                injectedMessage={injectedMessage}
              />
            </ErrorBoundary>
          ) : (
            <ErrorBoundary label="Artifacts">
              <ArtifactsPanel
                revision={artifactsRevision}
                onAddToMap={(geojson, name) => {
                  setMapActions((prev) => [
                    ...prev,
                    { type: 'add_geojson', payload: { geojson: geojson as FeatureCollection, name } },
                  ])
                }}
              />
            </ErrorBoundary>
          )}
        </aside>
      </div>
      <StreetViewDialog target={streetViewTarget} onClose={() => setStreetViewTarget(null)} />
    </div>
  )
}

export default App
