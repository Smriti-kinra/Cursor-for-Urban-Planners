import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import MapView from './components/MapView'
import FileTree from './components/FileTree'
import ChatPanel from './components/ChatPanel'
import ArtifactsPanel from './components/ArtifactsPanel'
import LayerPanel from './components/LayerPanel'
import {
  GeoJSONLayer,
  MapViewState,
  Conversation,
  MapAction,
  MapContext,
  ProjectData,
  LAYER_COLORS,
} from './types'

type LeftTab = 'files' | 'layers'
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
  const [mapAction, setMapAction] = useState<MapAction | null>(null)

  const colorIndexRef = useRef(0)
  const isLoadingRef = useRef(false)
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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

  // ── Map context for AI ──

  const mapContext: MapContext = useMemo(
    () => ({
      center: mapViewState.center,
      zoom: mapViewState.zoom,
      layers: layers.map((l) => ({
        name: l.name,
        featureCount: l.data?.features?.length || 0,
        geometryTypes: [
          ...new Set(
            (l.data?.features || [])
              .map((f: any) => f.geometry?.type)
              .filter(Boolean) as string[],
          ),
        ],
        properties: [
          ...new Set(
            (l.data?.features || []).flatMap((f: any) =>
              Object.keys(f.properties || {}),
            ) as string[],
          ),
        ],
      })),
      drawnFeatureCount: drawnFeatures.length,
      basemap,
    }),
    [mapViewState, layers, drawnFeatures, basemap],
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
      version: 1,
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
    }
    await window.electronAPI.writeFile(
      `${workspacePath}/project.json`,
      JSON.stringify(projectData, null, 2),
    )
  }, [workspacePath, mapViewState, layers, drawnFeatures, conversations, activeConversationId, basemap])

  const loadProject = useCallback(async () => {
    if (!workspacePath) return
    isLoadingRef.current = true
    try {
      const content = await window.electronAPI.readFile(`${workspacePath}/project.json`)
      if (!content) {
        isLoadingRef.current = false
        return
      }
      const data: ProjectData = JSON.parse(content)
      if (data.mapState) {
        setMapViewState(data.mapState)
        setMapAction({ type: 'set_view', payload: data.mapState })
      }
      if (data.basemap) setBasemap(data.basemap)
      if (data.drawnFeatures) setDrawnFeatures(data.drawnFeatures)

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
  }, [workspacePath, mapViewState, layers, drawnFeatures, conversations, activeConversationId, basemap, saveProject])

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
          <div className="tab-bar">
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
          </div>
          {activeLeftTab === 'files' ? (
            <FileTree workspacePath={workspacePath} onFileClick={handleFileClick} />
          ) : (
            <LayerPanel layers={layers} onToggle={toggleLayer} onRemove={removeLayer} />
          )}
        </aside>

        {/* Left resize handle */}
        <div className="resize-handle" onMouseDown={onResizeStart('left')} />

        {/* Center */}
        <main className="center-panel">
          <MapView
            layers={layers}
            basemap={basemap}
            drawMode={drawMode}
            initialState={mapViewState}
            drawnFeatures={drawnFeatures}
            mapAction={mapAction}
            onMapMove={setMapViewState}
            onBasemapChange={setBasemap}
            onDrawModeChange={setDrawMode}
            onDrawChange={setDrawnFeatures}
            onSaveDrawing={handleSaveDrawing}
            onActionHandled={() => setMapAction(null)}
          />
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
              onMapAction={setMapAction}
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
