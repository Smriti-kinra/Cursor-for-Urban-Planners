import { useEffect, useRef, useState, useCallback } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import {
  TerraDraw,
  TerraDrawPolygonMode,
  TerraDrawLineStringMode,
  TerraDrawPointMode,
  TerraDrawSelectMode,
  TerraDrawRenderMode,
} from 'terra-draw'
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter'
import * as turf from '@turf/turf'
import { GeoJSONLayer, MapViewState, MapAction, BASEMAPS } from '../types'
import './MapView.css'

interface MapViewProps {
  layers: GeoJSONLayer[]
  basemap: string
  drawMode: string | null
  initialState: MapViewState
  drawnFeatures: any[]
  mapAction: MapAction | null
  onMapMove: (state: MapViewState) => void
  onBasemapChange: (basemap: string) => void
  onDrawModeChange: (mode: string | null) => void
  onDrawChange: (features: any[]) => void
  onSaveDrawing: () => void
  onActionHandled: () => void
}

const DRAW_MODES = [
  { id: 'polygon', label: 'Polygon', icon: '⬡' },
  { id: 'linestring', label: 'Line', icon: '╱' },
  { id: 'point', label: 'Point', icon: '●' },
  { id: 'select', label: 'Select', icon: '✥' },
]

export default function MapView({
  layers,
  basemap,
  drawMode,
  initialState,
  drawnFeatures,
  mapAction,
  onMapMove,
  onBasemapChange,
  onDrawModeChange,
  onDrawChange,
  onSaveDrawing,
  onActionHandled,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const drawRef = useRef<TerraDraw | null>(null)
  const mapReadyRef = useRef(false)
  const onDrawChangeRef = useRef(onDrawChange)
  onDrawChangeRef.current = onDrawChange
  const ownLayerIds = useRef(new Set<string>())

  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [showBasemaps, setShowBasemaps] = useState(false)
  const [measurement, setMeasurement] = useState<{
    area: number
    length: number
    points: number
  } | null>(null)

  const ensureBasemapBottom = useCallback((map: maplibregl.Map) => {
    const styleLayers = map.getStyle()?.layers
    if (!styleLayers || styleLayers.length === 0) return
    if (styleLayers[0]?.id === 'basemap') return
    const nonBasemapFirst = styleLayers.find((l) => l.id !== 'basemap')
    if (nonBasemapFirst && map.getLayer('basemap')) {
      map.moveLayer('basemap', nonBasemapFirst.id)
    }
  }, [])

  // ── Initialize map ──

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const { tiles, attribution } = BASEMAPS[basemap] || BASEMAPS.street

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          basemap: { type: 'raster', tiles, tileSize: 256, attribution },
        },
        layers: [
          { id: 'basemap', type: 'raster', source: 'basemap', minzoom: 0, maxzoom: 19 },
        ],
      },
      center: initialState.center,
      zoom: initialState.zoom,
      bearing: initialState.bearing || 0,
      pitch: initialState.pitch || 0,
    })

    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.addControl(new maplibregl.ScaleControl(), 'bottom-left')

    map.on('moveend', () => {
      onMapMove({
        center: [map.getCenter().lng, map.getCenter().lat],
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch(),
      })
    })

    mapRef.current = map

    map.on('load', () => {
      mapReadyRef.current = true

      try {
        if (drawRef.current) return

        const draw = new TerraDraw({
          adapter: new TerraDrawMapLibreGLAdapter({
            map,
            coordinatePrecision: 9,
          }),
          modes: [
            new TerraDrawPolygonMode({
              styles: {
                fillColor: '#3b82f6',
                fillOpacity: 0.25,
                outlineColor: '#2563eb',
                outlineWidth: 2,
                closingPointColor: '#2563eb',
                closingPointOutlineColor: '#ffffff',
                closingPointOutlineWidth: 2,
                closingPointWidth: 6,
              },
            }),
            new TerraDrawLineStringMode({
              styles: {
                lineStringColor: '#ef4444',
                lineStringWidth: 3,
                closingPointColor: '#ef4444',
                closingPointOutlineColor: '#ffffff',
                closingPointOutlineWidth: 2,
                closingPointWidth: 6,
              },
            }),
            new TerraDrawPointMode({
              styles: {
                pointColor: '#f59e0b',
                pointOutlineColor: '#ffffff',
                pointOutlineWidth: 2,
                pointWidth: 8,
              },
            }),
            new TerraDrawSelectMode({
              flags: {
                polygon: {
                  feature: {
                    draggable: true,
                    coordinates: { midpoints: true, draggable: true, deletable: true },
                  },
                },
                linestring: {
                  feature: {
                    draggable: true,
                    coordinates: { midpoints: true, draggable: true, deletable: true },
                  },
                },
                point: { feature: { draggable: true } },
              },
            }),
            new TerraDrawRenderMode({ modeName: 'static', styles: {} }),
          ],
        })

        draw.start()

        draw.on('change', () => {
          const snapshot = draw.getSnapshot()
          onDrawChangeRef.current(snapshot)
        })

        drawRef.current = draw
        ensureBasemapBottom(map)
      } catch (err) {
        console.error('Failed to initialize TerraDraw:', err)
      }
    })

    return () => {
      mapReadyRef.current = false
      if (drawRef.current) {
        drawRef.current.stop()
        drawRef.current = null
      }
      map.remove()
      mapRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sync GeoJSON layers (only touches our own layer-* sources) ──

  const syncLayers = useCallback(
    (map: maplibregl.Map) => {
      const style = map.getStyle()
      if (!style) return

      const desiredIds = new Set(layers.map((l) => l.id))

      for (const id of ownLayerIds.current) {
        if (!desiredIds.has(id)) {
          for (const suffix of ['-fill', '-outline', '-line', '-circle']) {
            if (map.getLayer(`${id}${suffix}`)) map.removeLayer(`${id}${suffix}`)
          }
          if (map.getSource(id)) map.removeSource(id)
          ownLayerIds.current.delete(id)
        }
      }

      for (const layer of layers) {
        if (!map.getSource(layer.id)) {
          map.addSource(layer.id, { type: 'geojson', data: layer.data })
          ownLayerIds.current.add(layer.id)

          map.addLayer({
            id: `${layer.id}-fill`,
            type: 'fill',
            source: layer.id,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Polygon'],
              ['==', ['geometry-type'], 'MultiPolygon'],
            ],
            paint: { 'fill-color': layer.color, 'fill-opacity': 0.3 },
            layout: { visibility: layer.visible ? 'visible' : 'none' },
          })

          map.addLayer({
            id: `${layer.id}-outline`,
            type: 'line',
            source: layer.id,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Polygon'],
              ['==', ['geometry-type'], 'MultiPolygon'],
            ],
            paint: { 'line-color': layer.color, 'line-width': 2 },
            layout: { visibility: layer.visible ? 'visible' : 'none' },
          })

          map.addLayer({
            id: `${layer.id}-line`,
            type: 'line',
            source: layer.id,
            filter: [
              'any',
              ['==', ['geometry-type'], 'LineString'],
              ['==', ['geometry-type'], 'MultiLineString'],
            ],
            paint: { 'line-color': layer.color, 'line-width': 2 },
            layout: { visibility: layer.visible ? 'visible' : 'none' },
          })

          map.addLayer({
            id: `${layer.id}-circle`,
            type: 'circle',
            source: layer.id,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Point'],
              ['==', ['geometry-type'], 'MultiPoint'],
            ],
            paint: {
              'circle-color': layer.color,
              'circle-radius': 6,
              'circle-stroke-color': '#ffffff',
              'circle-stroke-width': 1.5,
            },
            layout: { visibility: layer.visible ? 'visible' : 'none' },
          })

          try {
            const bbox = turf.bbox(layer.data) as [number, number, number, number]
            if (bbox.every((v) => isFinite(v))) {
              map.fitBounds(bbox, { padding: 60, maxZoom: 16, duration: 1000 })
            }
          } catch {
            /* ignore invalid bbox */
          }
        } else {
          const vis = layer.visible ? 'visible' : 'none'
          for (const suffix of ['-fill', '-outline', '-line', '-circle']) {
            if (map.getLayer(`${layer.id}${suffix}`)) {
              map.setLayoutProperty(`${layer.id}${suffix}`, 'visibility', vis)
            }
          }
        }
      }

      ensureBasemapBottom(map)
    },
    [layers, ensureBasemapBottom],
  )

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReadyRef.current) return
    syncLayers(map)
  }, [layers, syncLayers])

  // ── Basemap switching ──

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReadyRef.current) return

    const { tiles, attribution } = BASEMAPS[basemap] || BASEMAPS.street

    if (map.getLayer('basemap')) map.removeLayer('basemap')
    if (map.getSource('basemap')) map.removeSource('basemap')

    map.addSource('basemap', {
      type: 'raster',
      tiles,
      tileSize: 256,
      attribution,
    } as any)

    map.addLayer({ id: 'basemap', type: 'raster', source: 'basemap', minzoom: 0, maxzoom: 19 })
    ensureBasemapBottom(map)
  }, [basemap, ensureBasemapBottom])

  // ── Draw mode ──

  useEffect(() => {
    if (!drawRef.current) return
    try {
      drawRef.current.setMode(drawMode || 'static')
    } catch (err) {
      console.error('TerraDraw setMode failed:', drawMode, err)
    }
  }, [drawMode])

  // ── Measurement ──

  useEffect(() => {
    if (drawnFeatures.length === 0) {
      setMeasurement(null)
      return
    }

    let area = 0,
      length = 0,
      points = 0
    for (const f of drawnFeatures) {
      if (!f.geometry) continue
      try {
        const t = f.geometry.type
        if (t === 'Polygon' || t === 'MultiPolygon') area += turf.area(f)
        if (t === 'LineString' || t === 'MultiLineString')
          length += turf.length(f, { units: 'kilometers' })
        if (t === 'Point') points++
      } catch {
        /* skip invalid geometries */
      }
    }
    setMeasurement({ area, length, points })
  }, [drawnFeatures])

  // ── Map actions (fly_to, highlight, set_view) ──

  useEffect(() => {
    if (!mapAction || !mapRef.current) return
    const map = mapRef.current

    if (mapAction.type === 'fly_to') {
      map.flyTo({
        center: [mapAction.payload.lng, mapAction.payload.lat],
        zoom: mapAction.payload.zoom || 15,
        duration: 2000,
      })
    } else if (mapAction.type === 'set_view') {
      map.jumpTo({
        center: mapAction.payload.center,
        zoom: mapAction.payload.zoom,
        bearing: mapAction.payload.bearing || 0,
        pitch: mapAction.payload.pitch || 0,
      })
    } else if (mapAction.type === 'highlight_features') {
      const { layer_name, property_name, property_value } = mapAction.payload
      const target = layers.find((l) => l.name.toLowerCase() === layer_name?.toLowerCase())
      if (target) {
        const filtered = (target.data.features || []).filter(
          (f: any) => String(f.properties?.[property_name]) === String(property_value),
        )
        if (filtered.length > 0) {
          const hlId = 'highlight-temp'
          if (map.getSource(hlId)) {
            if (map.getLayer(`${hlId}-fill`)) map.removeLayer(`${hlId}-fill`)
            if (map.getLayer(`${hlId}-line`)) map.removeLayer(`${hlId}-line`)
            map.removeSource(hlId)
          }
          map.addSource(hlId, {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: filtered },
          })
          map.addLayer({
            id: `${hlId}-fill`,
            type: 'fill',
            source: hlId,
            paint: { 'fill-color': '#ffff00', 'fill-opacity': 0.5 },
          })
          map.addLayer({
            id: `${hlId}-line`,
            type: 'line',
            source: hlId,
            paint: { 'line-color': '#ffff00', 'line-width': 3 },
          })
          try {
            const bbox = turf.bbox({
              type: 'FeatureCollection',
              features: filtered,
            }) as [number, number, number, number]
            if (bbox.every((v) => isFinite(v))) {
              map.fitBounds(bbox, { padding: 60, maxZoom: 16, duration: 1000 })
            }
          } catch {
            /* ignore */
          }
          setTimeout(() => {
            if (!mapRef.current) return
            const m = mapRef.current
            if (m.getLayer(`${hlId}-fill`)) m.removeLayer(`${hlId}-fill`)
            if (m.getLayer(`${hlId}-line`)) m.removeLayer(`${hlId}-line`)
            if (m.getSource(hlId)) m.removeSource(hlId)
          }, 10000)
        }
      }
    }

    onActionHandled()
  }, [mapAction]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Geocoding search ──

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    try {
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(searchQuery)}&format=json&limit=5`,
        { headers: { 'User-Agent': 'CursorUrbanPlanners/1.0' } },
      )
      setSearchResults(await resp.json())
    } catch {
      setSearchResults([])
    }
  }

  const flyToResult = (result: any) => {
    mapRef.current?.flyTo({
      center: [parseFloat(result.lon), parseFloat(result.lat)],
      zoom: 15,
      duration: 2000,
    })
    setSearchResults([])
    setShowSearch(false)
    setSearchQuery('')
  }

  // ── Delete drawn features ──

  const handleDeleteDrawn = () => {
    if (!drawRef.current) return
    const snapshot = drawRef.current.getSnapshot()
    const ids = snapshot.map((f) => f.id as string)
    if (ids.length > 0) {
      try {
        drawRef.current.removeFeatures(ids)
      } catch {
        /* ignore */
      }
    }
    onDrawChange([])
  }

  const formatMeasurement = () => {
    if (!measurement) return null
    const parts: string[] = []
    if (measurement.area > 0) {
      if (measurement.area < 10000) parts.push(`${measurement.area.toFixed(0)} m²`)
      else if (measurement.area < 1000000)
        parts.push(`${(measurement.area / 10000).toFixed(2)} ha`)
      else parts.push(`${(measurement.area / 1000000).toFixed(2)} km²`)
    }
    if (measurement.length > 0) {
      if (measurement.length < 1) parts.push(`${(measurement.length * 1000).toFixed(0)} m`)
      else parts.push(`${measurement.length.toFixed(2)} km`)
    }
    if (measurement.points > 0)
      parts.push(`${measurement.points} pt${measurement.points > 1 ? 's' : ''}`)
    return parts.length > 0 ? parts.join(' · ') : null
  }

  return (
    <div className="map-view">
      <div ref={containerRef} className="map-container" />

      {/* ── Toolbar ── */}
      <div className="map-toolbar">
        <button
          className={`toolbar-btn ${showSearch ? 'active' : ''}`}
          onClick={() => {
            setShowSearch(!showSearch)
            setShowBasemaps(false)
          }}
          title="Search"
        >
          🔍
        </button>

        <div className="toolbar-divider" />

        {DRAW_MODES.map((mode) => (
          <button
            key={mode.id}
            className={`toolbar-btn ${drawMode === mode.id ? 'active' : ''}`}
            onClick={() => onDrawModeChange(drawMode === mode.id ? null : mode.id)}
            title={mode.label}
          >
            {mode.icon}
          </button>
        ))}

        {drawnFeatures.length > 0 && (
          <>
            <div className="toolbar-divider" />
            <button className="toolbar-btn save" onClick={onSaveDrawing} title="Save drawing">
              💾
            </button>
            <button
              className="toolbar-btn danger"
              onClick={handleDeleteDrawn}
              title="Delete all drawings"
            >
              🗑
            </button>
          </>
        )}

        <div className="toolbar-spacer" />

        <button
          className={`toolbar-btn ${showBasemaps ? 'active' : ''}`}
          onClick={() => {
            setShowBasemaps(!showBasemaps)
            setShowSearch(false)
          }}
          title="Basemaps"
        >
          🗺
        </button>
      </div>

      {/* ── Search panel ── */}
      {showSearch && (
        <div className="search-panel">
          <div className="search-input-row">
            <input
              className="search-input"
              placeholder="Search for a place..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              autoFocus
            />
            <button className="search-go" onClick={handleSearch}>
              Go
            </button>
          </div>
          {searchResults.length > 0 && (
            <div className="search-results">
              {searchResults.map((r: any, i: number) => (
                <div key={i} className="search-result" onClick={() => flyToResult(r)}>
                  {r.display_name}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Basemap switcher ── */}
      {showBasemaps && (
        <div className="basemap-panel">
          {Object.entries(BASEMAPS).map(([key, info]) => (
            <button
              key={key}
              className={`basemap-option ${basemap === key ? 'active' : ''}`}
              onClick={() => {
                onBasemapChange(key)
                setShowBasemaps(false)
              }}
            >
              {info.name}
            </button>
          ))}
        </div>
      )}

      {/* ── Measurement overlay ── */}
      {formatMeasurement() && (
        <div className="measurement-overlay">{formatMeasurement()}</div>
      )}
    </div>
  )
}
