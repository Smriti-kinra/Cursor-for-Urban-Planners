import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import * as turf from '@turf/turf'
import MapView, { type MapViewHandle } from './components/MapView'
import FileTree from './components/FileTree'
import ChatPanel from './components/ChatPanel'
import ArtifactsPanel from './components/ArtifactsPanel'
import LayerPanel from './components/LayerPanel'
import BookmarkPanel from './components/BookmarkPanel'
import ExportPanel from './components/ExportPanel'
import DrawToolbar from './components/DrawToolbar'
import ZoningPanel from './components/ZoningPanel'
import {
  GeoJSONLayer,
  MapViewState,
  Conversation,
  MapAction,
  MapContext,
  ProjectData,
  LAYER_COLORS,
  MapBookmark,
  DrawStyleConfig,
  DEFAULT_DRAW_STYLE,
  ZonePreset,
  DEFAULT_ZONE_PRESETS,
} from './types'

type LeftTab = 'files' | 'layers' | 'bookmarks' | 'export' | 'zoning'
type RightTab = 'chat' | 'artifacts'

function genId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function App() {
  const [workspacePath, setWorkspacePath] = useState<string | null>(null)
  const [activeLeftTab, setActiveLeftTab] = useState<LeftTab>('files')
  const [activeRightTab, setActiveRightTab] = useState<RightTab>('chat')

  const [layers, setLayers] = useState<GeoJSONLayer[]>([])
  const [mapViewState, setMapViewState] = useState<MapViewState>({
    center: [-73.985, 40.748],
    zoom: 13,
    bearing: 0,
    pitch: 0,
  })
  const [basemap, setBasemap] = useState('street')
  const [drawMode, setDrawMode] = useState<string | null>(null)
  const [drawnFeatures, setDrawnFeatures] = useState<any[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [mapActions, setMapActions] = useState<MapAction[]>([])
  const [bookmarks, setBookmarks] = useState<MapBookmark[]>([])
  const [mapBounds, setMapBounds] = useState<{
    west: number
    south: number
    east: number
    north: number
  } | null>(null)
  const [drawStyle, setDrawStyle] = useState<DrawStyleConfig>(DEFAULT_DRAW_STYLE)
  const [activeZonePreset, setActiveZonePreset] = useState<ZonePreset | null>(null)
  const [drawHistory, setDrawHistory] = useState({ canUndo: false, canRedo: false })

  const mapViewRef = useRef<MapViewHandle>(null)
  const bookmarksRef = useRef<MapBookmark[]>([])
  const mapBoundsRef = useRef<typeof mapBounds>(null)

  const colorIndexRef = useRef(0)
  const isLoadingRef = useRef(false)
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    bookmarksRef.current = bookmarks
  }, [bookmarks])
  useEffect(() => {
    mapBoundsRef.current = mapBounds
  }, [mapBounds])

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

  const handleSelectWorkspace = async (): Promise<void> => {
    const selected = await window.electronAPI.selectWorkspace()
    if (selected) setWorkspacePath(selected)
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

  const handleFileClick = useCallback(
    (entry: FileEntry) => {
      if (entry.name.toLowerCase().endsWith('.geojson')) {
        addLayer(entry.name.replace(/\.geojson$/i, ''), entry.path)
      }
    },
    [addLayer],
  )

  const handleSaveDrawing = useCallback(async () => {
    if (!workspacePath || drawnFeatures.length === 0) return
    const fc = { type: 'FeatureCollection', features: drawnFeatures }
    const fileName = `drawing-${Date.now()}.geojson`
    const filePath = `${workspacePath}/${fileName}`
    await window.electronAPI.writeFile(filePath, JSON.stringify(fc, null, 2))
    addLayer(fileName.replace('.geojson', ''), filePath)
  }, [workspacePath, drawnFeatures, addLayer])

  const handleDrawFeaturesChange = useCallback(
    (features: any[]) => {
      let next = features
      if (activeZonePreset) {
        next = features.map((f) => ({
          ...f,
          properties: {
            ...(f.properties || {}),
            zone_code: activeZonePreset.code,
            zone_label: activeZonePreset.label,
          },
        }))
      }
      setDrawnFeatures(next)
      queueMicrotask(() => {
        setDrawHistory({
          canUndo: mapViewRef.current?.canUndoDraw() ?? false,
          canRedo: mapViewRef.current?.canRedoDraw() ?? false,
        })
      })
    },
    [activeZonePreset],
  )

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
    pdf.setFontSize(14)
    pdf.text('Map export — Cursor for Urban Planners', 40, 40)
    pdf.addImage(img, 'PNG', 40, 55, 760, 520)
    pdf.save(`map-report-${Date.now()}.pdf`)
  }, [])

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
      const allFeatures: any[] = []
      for (const layer of layers) {
        for (const f of layer.data?.features || []) {
          try {
            const clipped = turf.bboxClip(f as any, bbox) as any
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

  const upsertLayer = useCallback((layerName: string, data: any, color?: string) => {
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

  // ── Map action handler (intercepts layer ops, queues the rest) ──

  const handleMapAction = useCallback((action: MapAction) => {
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
      const data =
        geojson?.type === 'FeatureCollection'
          ? geojson
          : geojson?.type === 'Feature'
            ? { type: 'FeatureCollection', features: [geojson] }
            : { type: 'FeatureCollection', features: [] }
      upsertLayer(name || 'AI Layer', data, color)
      return
    }
    if (action.type === 'draw_line') {
      const { coordinates, color, label } = action.payload
      const data = {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: coordinates || [] },
          properties: { label: label || '' },
        }],
      }
      upsertLayer(label || 'Drawn Line', data, color || '#ef4444')
      return
    }
    if (action.type === 'draw_polygon') {
      const { coordinates: rawCoords, color, label } = action.payload
      const coords = rawCoords || []
      const ring =
        coords.length >= 3 &&
        (coords[0][0] !== coords[coords.length - 1][0] ||
          coords[0][1] !== coords[coords.length - 1][1])
          ? [...coords, coords[0]]
          : coords
      const data = {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [ring] },
          properties: { label: label || '' },
        }],
      }
      upsertLayer(label || 'Drawn Polygon', data, color || '#3b82f6')
      return
    }
    if (action.type === 'draw_circle') {
      const { center_lat, center_lng, radius_km, color, label } = action.payload
      const circle = turf.circle(
        [center_lng, center_lat],
        radius_km,
        { units: 'kilometers', steps: 64 },
      )
      const data = { type: 'FeatureCollection', features: [circle] }
      upsertLayer(label || `Circle (${radius_km} km)`, data, color || '#8b5cf6')
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
    if (action.type === 'refresh_artifacts') return
    setMapActions((prev) => [...prev, action])
  }, [upsertLayer, clipLayersToBboxAndSave, mapViewState.zoom])

  // ── Map context for AI ──

  const mapContext: MapContext = useMemo(
    () => ({
      center: mapViewState.center,
      zoom: mapViewState.zoom,
      bounds: mapBounds
        ? {
            west: mapBounds.west,
            south: mapBounds.south,
            east: mapBounds.east,
            north: mapBounds.north,
          }
        : undefined,
      bookmarks: bookmarks.map((b) => ({
        name: b.name,
        south: b.south,
        west: b.west,
        north: b.north,
        east: b.east,
        zoom: b.zoom,
      })),
      layers: layers.map((l) => {
        const features = l.data?.features || []
        const featureCount = features.length
        const geometryTypes = [
          ...new Set(
            features.map((f: any) => f.geometry?.type).filter(Boolean) as string[],
          ),
        ]
        const properties = [
          ...new Set(
            features.flatMap((f: any) =>
              Object.keys(f.properties || {}),
            ) as string[],
          ),
        ].slice(0, 20)

        // Include actual coordinates for small layers (≤5 features) so the
        // LLM can compute centroids, buffers, intersections, etc.
        let geometry_data: any = undefined
        const totalCoords = features.reduce((sum: number, f: any) => {
          const c = f.geometry?.coordinates
          if (!c) return sum
          if (f.geometry.type === 'Point') return sum + 1
          if (f.geometry.type === 'LineString') return sum + c.length
          if (f.geometry.type === 'Polygon') return sum + (c[0]?.length || 0)
          if (f.geometry.type === 'MultiPolygon')
            return sum + c.reduce((s: number, p: any) => s + (p[0]?.length || 0), 0)
          return sum + 10
        }, 0)

        if (featureCount <= 5 && totalCoords <= 200) {
          geometry_data = features.map((f: any) => ({
            type: f.geometry?.type,
            coordinates: f.geometry?.coordinates,
          }))
        } else {
          try {
            const bbox = turf.bbox(l.data) as [number, number, number, number]
            if (bbox.every((v) => isFinite(v))) {
              geometry_data = { bbox }
            }
          } catch { /* ignore */ }
        }

        return {
          name: l.name,
          featureCount,
          geometryTypes,
          properties,
          visible: l.visible,
          ...(geometry_data ? { geometry_data } : {}),
        }
      }),
      drawnFeatures: drawnFeatures.slice(0, 10).map((f: any) => ({
        type: f.geometry?.type || 'unknown',
        coordinates: f.geometry?.coordinates,
      })),
      basemap,
    }),
    [mapViewState, mapBounds, bookmarks, layers, drawnFeatures, basemap],
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

  const saveProject = useCallback(async () => {
    if (!workspacePath || isLoadingRef.current) return
    const projectData: ProjectData = {
      version: 2,
      mapState: mapViewState,
      layers: layers.map((l) => ({
        name: l.name,
        filePath: l.filePath,
        visible: l.visible,
        color: l.color,
      })),
      drawnFeatures,
      conversations,
      activeConversationId,
      basemap,
      bookmarks,
    }
    await window.electronAPI.writeFile(
      `${workspacePath}/project.json`,
      JSON.stringify(projectData, null, 2),
    )
  }, [workspacePath, mapViewState, layers, drawnFeatures, conversations, activeConversationId, basemap, bookmarks])

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
      if (data.drawnFeatures) setDrawnFeatures(data.drawnFeatures)
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
        for (const info of data.layers) {
          const fileContent = await window.electronAPI.readFile(info.filePath)
          if (!fileContent) continue
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
              filePath: info.filePath,
              visible: info.visible,
              data: geojson,
              color: info.color,
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
    if (!workspacePath || isLoadingRef.current) return
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    saveTimeoutRef.current = setTimeout(saveProject, 2000)
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    }
  }, [workspacePath, mapViewState, layers, drawnFeatures, conversations, activeConversationId, basemap, bookmarks, saveProject])

  const workspaceLabel = workspacePath ? workspacePath.split('/').pop() : 'Open Workspace'

  return (
    <div className="app">
      <header className="titlebar">
        <div className="titlebar-drag" />
        <span className="titlebar-text">Cursor for Urban Planners</span>
        <button className="workspace-btn" onClick={handleSelectWorkspace}>
          {workspaceLabel}
        </button>
      </header>

      <div className="layout">
        {/* Left panel */}
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
            <FileTree workspacePath={workspacePath} onFileClick={handleFileClick} />
          )}
          {activeLeftTab === 'layers' && (
            <LayerPanel layers={layers} onToggle={toggleLayer} onRemove={removeLayer} />
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
            />
          )}
          {activeLeftTab === 'zoning' && <ZoningPanel />}
        </aside>

        {/* Left resize handle */}
        <div className="resize-handle" onMouseDown={onResizeStart('left')} />

        {/* Center */}
        <main className="center-panel">
          <div className="map-stack">
            <MapView
              ref={mapViewRef}
              layers={layers}
              basemap={basemap}
              drawMode={drawMode}
              initialState={mapViewState}
              drawnFeatures={drawnFeatures}
              mapActions={mapActions}
              drawStyle={drawStyle}
              onMapMove={setMapViewState}
              onBoundsChange={setMapBounds}
              onBasemapChange={setBasemap}
              onDrawModeChange={setDrawMode}
              onDrawChange={handleDrawFeaturesChange}
              onDrawHistoryChange={setDrawHistory}
              onSaveDrawing={handleSaveDrawing}
              onActionsProcessed={() => setMapActions([])}
            />
            <DrawToolbar
              drawStyle={drawStyle}
              onDrawStyleChange={(partial) => setDrawStyle((s) => ({ ...s, ...partial }))}
              activeZonePreset={activeZonePreset}
              onZonePresetChange={setActiveZonePreset}
              zonePresets={DEFAULT_ZONE_PRESETS}
              onUndo={() => {
                mapViewRef.current?.undoDraw()
                queueMicrotask(() =>
                  setDrawHistory({
                    canUndo: mapViewRef.current?.canUndoDraw() ?? false,
                    canRedo: mapViewRef.current?.canRedoDraw() ?? false,
                  }),
                )
              }}
              onRedo={() => {
                mapViewRef.current?.redoDraw()
                queueMicrotask(() =>
                  setDrawHistory({
                    canUndo: mapViewRef.current?.canUndoDraw() ?? false,
                    canRedo: mapViewRef.current?.canRedoDraw() ?? false,
                  }),
                )
              }}
              canUndo={drawHistory.canUndo}
              canRedo={drawHistory.canRedo}
            />
          </div>
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
            <button
              className={`tab ${activeRightTab === 'artifacts' ? 'active' : ''}`}
              onClick={() => setActiveRightTab('artifacts')}
            >
              Artifacts
            </button>
          </div>
          {activeRightTab === 'chat' ? (
            <ChatPanel
              conversations={conversations}
              activeConversation={activeConversation}
              onCreateConversation={handleCreateConversation}
              onSelectConversation={handleSelectConversation}
              onDeleteConversation={handleDeleteConversation}
              onMessagesChange={handleConversationMessagesChange}
              mapContext={mapContext}
              onMapAction={handleMapAction}
            />
          ) : (
            <ArtifactsPanel />
          )}
        </aside>
      </div>
    </div>
  )
}

export default App
