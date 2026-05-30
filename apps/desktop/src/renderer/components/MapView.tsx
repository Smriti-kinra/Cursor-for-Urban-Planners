import { useEffect, useRef, useState, forwardRef, useImperativeHandle } from 'react'
import maplibregl from 'maplibre-gl'
import type { DataDrivenPropertyValueSpecification, ExpressionSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import * as turf from '@turf/turf'
import type { Feature, FeatureCollection } from 'geojson'
import { GeoJSONLayer, MapViewState, MapAction, BASEMAPS } from '../types'
import './MapView.css'

interface NominatimSearchResult {
  display_name: string
  lat: string
  lon: string
}

export type MapViewHandle = {
  getCanvas: () => HTMLCanvasElement | null
}

// Labels are the most expensive layer type. Above this feature count we skip
// the symbol layer entirely to keep the map responsive.
const LABEL_FEATURE_CAP = 3000

// ── Data-driven paint expressions ──
//
// Translate a layer's styleSpec into a MapLibre color expression. Always wrap
// in coalesce(get(fillColor|strokeColor), <expr>) so a per-feature color
// override still wins over categorized/graduated styling.

type ColorExpr = DataDrivenPropertyValueSpecification<string>

function categorizedExpr(spec: NonNullable<GeoJSONLayer['styleSpec']>, fallback: string): unknown {
  const match: unknown[] = ['match', ['to-string', ['get', spec.property!]]]
  for (const c of spec.categories!) match.push(c.value, c.color)
  match.push(spec.otherColor || fallback) // default for unmatched values
  return match
}

function graduatedExpr(spec: NonNullable<GeoJSONLayer['styleSpec']>, fallback: string): unknown {
  const colors = spec.rampColors!
  const step: unknown[] = ['step', ['to-number', ['get', spec.property!], 0], colors[0]]
  spec.breaks!.forEach((b, i) => step.push(b, colors[i + 1] ?? colors[colors.length - 1]))
  return step
}

function dataDrivenColor(
  spec: GeoJSONLayer['styleSpec'],
  overrideProp: 'fillColor' | 'strokeColor',
  scalar: string,
): ColorExpr {
  if (spec && spec.mode === 'categorized' && spec.property && spec.categories?.length) {
    return ['coalesce', ['get', overrideProp], categorizedExpr(spec, scalar)] as ColorExpr
  }
  if (
    spec && spec.mode === 'graduated' && spec.property &&
    spec.breaks?.length && spec.rampColors?.length
  ) {
    return ['coalesce', ['get', overrideProp], graduatedExpr(spec, scalar)] as ColorExpr
  }
  return ['coalesce', ['get', overrideProp], scalar] as ColorExpr
}

function fillColorExpression(layer: GeoJSONLayer): ColorExpr {
  return dataDrivenColor(layer.styleSpec, 'fillColor', layer.fillColor || layer.color)
}

function lineColorExpression(layer: GeoJSONLayer): ColorExpr {
  return dataDrivenColor(layer.styleSpec, 'strokeColor', layer.lineColor || layer.color)
}

function fillOpacityValue(layer: GeoJSONLayer): number {
  return layer.styleSpec?.opacity ?? layer.opacity ?? 0.3
}

function labelsActive(layer: GeoJSONLayer): boolean {
  const l = layer.styleSpec?.label
  return Boolean(
    l?.enabled && l.property &&
    (layer.data?.features?.length ?? 0) <= LABEL_FEATURE_CAP,
  )
}

/** text-field value for a layer's label symbol layer ('' = nothing drawn). */
function labelField(layer: GeoJSONLayer): ExpressionSpecification | string {
  const l = layer.styleSpec?.label
  return labelsActive(layer) ? (['get', l!.property] as ExpressionSpecification) : ''
}

interface MapViewProps {
  layers: GeoJSONLayer[]
  basemap: string
  initialState: MapViewState
  mapActions: MapAction[]
  onMapMove: (state: MapViewState) => void
  onBoundsChange?: (b: { west: number; south: number; east: number; north: number }) => void
  onBasemapChange: (basemap: string) => void
  onActionsProcessed: () => void
  onLayerStyleChange?: (
    layerName: string,
    style: { fillColor?: string; lineColor?: string; opacity?: number },
  ) => void
  onAddMarker?: (lng: number, lat: number) => void
  onOpenStreetView?: (lng: number, lat: number) => void
  onAskChat?: (lng: number, lat: number) => void
}

const MapView = forwardRef<MapViewHandle, MapViewProps>(function MapView(
  {
    layers,
    basemap,
    initialState,
    mapActions,
    onMapMove,
    onBoundsChange,
    onBasemapChange,
    onActionsProcessed,
    onLayerStyleChange,
    onAddMarker,
    onOpenStreetView,
    onAskChat,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const onBoundsChangeRef = useRef(onBoundsChange)
  onBoundsChangeRef.current = onBoundsChange
  const onLayerStyleChangeRef = useRef(onLayerStyleChange)
  onLayerStyleChangeRef.current = onLayerStyleChange
  const onAddMarkerRef = useRef(onAddMarker)
  onAddMarkerRef.current = onAddMarker
  const onOpenStreetViewRef = useRef(onOpenStreetView)
  onOpenStreetViewRef.current = onOpenStreetView
  const onAskChatRef = useRef(onAskChat)
  onAskChatRef.current = onAskChat
  const ownLayerIds = useRef(new Set<string>())
  // Per-source revision token: setData() is only called when layer.data changes.
  const layerRevisionRef = useRef(new Map<string, FeatureCollection>())
  const initBasemapRef = useRef(basemap)

  const [mapReady, setMapReady] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<NominatimSearchResult[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [showBasemaps, setShowBasemaps] = useState(false)
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; lng: number; lat: number } | null>(null)

  // ── Initialize map ──

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const { tiles, attribution } = BASEMAPS[initBasemapRef.current] || BASEMAPS.street

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        // Glyphs are required for any symbol/text layer (feature labels).
        // demotiles serves free PBF font ranges with no API key, matching the
        // keyless raster-tile approach. Offline → labels just don't draw.
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
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
      // PNG/PDF export reads the canvas via toBlob/toDataURL. WebGL clears the
      // back-buffer after each frame composite by default, which makes those
      // reads return blank pixels. Trade ~10–20% GPU memory for working export.
      canvasContextAttributes: { preserveDrawingBuffer: true },
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
      const b = map.getBounds()
      onBoundsChangeRef.current?.({
        west: b.getWest(),
        south: b.getSouth(),
        east: b.getEast(),
        north: b.getNorth(),
      })
    })

    map.on('contextmenu', (e) => {
      e.preventDefault?.()
      setCtxMenu({ x: e.point.x, y: e.point.y, lng: e.lngLat.lng, lat: e.lngLat.lat })
    })
    map.on('movestart', () => setCtxMenu(null))

    mapRef.current = map

    map.on('load', () => {
      setMapReady(true)
    })

    return () => {
      setMapReady(false)
      layerRevisionRef.current.clear()
      map.remove()
      mapRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sync GeoJSON layers ──

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    const desiredIds = new Set(layers.map((l) => l.id))

    for (const id of ownLayerIds.current) {
      if (!desiredIds.has(id)) {
        for (const suffix of ['-fill', '-outline', '-line', '-circle', '-label']) {
          if (map.getLayer(`${id}${suffix}`)) map.removeLayer(`${id}${suffix}`)
        }
        if (map.getSource(id)) map.removeSource(id)
        ownLayerIds.current.delete(id)
        layerRevisionRef.current.delete(id)
      }
    }

    for (const layer of layers) {
      const fillOpacity = layer.opacity ?? 0.3

      if (!map.getSource(layer.id)) {
        map.addSource(layer.id, { type: 'geojson', data: layer.data })
        ownLayerIds.current.add(layer.id)
        layerRevisionRef.current.set(layer.id, layer.data)

        map.addLayer({
          id: `${layer.id}-fill`,
          type: 'fill',
          source: layer.id,
          filter: [
            'any',
            ['==', ['geometry-type'], 'Polygon'],
            ['==', ['geometry-type'], 'MultiPolygon'],
          ],
          paint: {
            'fill-color': fillColorExpression(layer),
            'fill-opacity': ['coalesce', ['get', 'fillOpacity'], fillOpacity] as DataDrivenPropertyValueSpecification<number>,
          },
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
          paint: {
            'line-color': lineColorExpression(layer),
            'line-width': 2,
          },
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
          paint: {
            'line-color': lineColorExpression(layer),
            'line-width': 2,
          },
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
            'circle-color': fillColorExpression(layer),
            'circle-radius': 6,
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 1.5,
          },
          layout: { visibility: layer.visible ? 'visible' : 'none' },
        })

        // Text labels (symbol layer). Requires the glyphs URL on the style.
        // minzoom keeps low-zoom views uncluttered; collision detection
        // (text-allow-overlap:false + text-optional) drops labels that don't fit.
        const labelSpec = layer.styleSpec?.label
        map.addLayer({
          id: `${layer.id}-label`,
          type: 'symbol',
          source: layer.id,
          minzoom: 10,
          layout: {
            'text-field': labelField(layer),
            // Must be a stack the glyphs endpoint actually serves. demotiles
            // provides 'Noto Sans Regular' (NOT 'Open Sans Regular' → 404).
            'text-font': ['Noto Sans Regular'],
            'text-size': labelSpec?.size ?? 12,
            'text-anchor': 'center',
            'text-allow-overlap': false,
            'text-optional': true,
            visibility: layer.visible && labelsActive(layer) ? 'visible' : 'none',
          },
          paint: {
            'text-color': labelSpec?.color ?? '#1f2937',
            'text-halo-color': labelSpec?.haloColor ?? '#ffffff',
            'text-halo-width': 1.2,
          },
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
        // Existing source — sync data + visibility + style overrides.
        const previous = layerRevisionRef.current.get(layer.id)
        if (previous !== layer.data) {
          const src = map.getSource(layer.id) as maplibregl.GeoJSONSource
          src.setData(layer.data)
          layerRevisionRef.current.set(layer.id, layer.data)
        }
        const vis = layer.visible ? 'visible' : 'none'
        for (const suffix of ['-fill', '-outline', '-line', '-circle']) {
          if (map.getLayer(`${layer.id}${suffix}`)) {
            map.setLayoutProperty(`${layer.id}${suffix}`, 'visibility', vis)
          }
        }
        if (map.getLayer(`${layer.id}-fill`)) {
          map.setPaintProperty(`${layer.id}-fill`, 'fill-color', fillColorExpression(layer))
          map.setPaintProperty(
            `${layer.id}-fill`, 'fill-opacity',
            ['coalesce', ['get', 'fillOpacity'], fillOpacity] as DataDrivenPropertyValueSpecification<number>,
          )
        }
        if (map.getLayer(`${layer.id}-outline`)) {
          map.setPaintProperty(`${layer.id}-outline`, 'line-color', lineColorExpression(layer))
        }
        if (map.getLayer(`${layer.id}-line`)) {
          map.setPaintProperty(`${layer.id}-line`, 'line-color', lineColorExpression(layer))
        }
        if (map.getLayer(`${layer.id}-circle`)) {
          map.setPaintProperty(`${layer.id}-circle`, 'circle-color', fillColorExpression(layer))
        }
        // Labels: re-apply field/size/color and visibility (gated by enabled +
        // feature cap, AND the layer's own visibility).
        if (map.getLayer(`${layer.id}-label`)) {
          const labelSpec = layer.styleSpec?.label
          map.setLayoutProperty(`${layer.id}-label`, 'text-field', labelField(layer))
          map.setLayoutProperty(`${layer.id}-label`, 'text-size', labelSpec?.size ?? 12)
          map.setLayoutProperty(
            `${layer.id}-label`, 'visibility',
            layer.visible && labelsActive(layer) ? 'visible' : 'none',
          )
          map.setPaintProperty(`${layer.id}-label`, 'text-color', labelSpec?.color ?? '#1f2937')
          map.setPaintProperty(`${layer.id}-label`, 'text-halo-color', labelSpec?.haloColor ?? '#ffffff')
        }
      }
    }
  }, [layers, mapReady])

  // ── Basemap switching ──

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    if (basemap === initBasemapRef.current && map.getSource('basemap')) return

    const { tiles, attribution } = BASEMAPS[basemap] || BASEMAPS.street

    if (map.getLayer('basemap')) map.removeLayer('basemap')
    if (map.getSource('basemap')) map.removeSource('basemap')

    map.addSource('basemap', {
      type: 'raster',
      tiles,
      tileSize: 256,
      attribution,
    })

    map.addLayer({ id: 'basemap', type: 'raster', source: 'basemap', minzoom: 0, maxzoom: 19 })

    const styleLayers = map.getStyle()?.layers
    if (styleLayers && styleLayers.length > 1 && styleLayers[styleLayers.length - 1]?.id === 'basemap') {
      const firstNonBasemap = styleLayers.find((l) => l.id !== 'basemap')
      if (firstNonBasemap) {
        map.moveLayer('basemap', firstNonBasemap.id)
      }
    }

    initBasemapRef.current = basemap
  }, [basemap, mapReady])

  useImperativeHandle(
    ref,
    () => ({
      getCanvas: () => mapRef.current?.getCanvas() ?? null,
    }),
    [mapReady],
  )

  // ── Map actions (all AI-driven actions) ──

  useEffect(() => {
    if (mapActions.length === 0 || !mapRef.current || !mapReady) return
    const map = mapRef.current

    for (const action of mapActions) {
      const { type, payload } = action

      switch (type) {
        case 'fly_to':
          map.flyTo({
            center: [payload.lng, payload.lat],
            zoom: payload.zoom || 15,
            duration: 2000,
          })
          break

        case 'fit_bounds':
          map.fitBounds(
            [
              [payload.west, payload.south],
              [payload.east, payload.north],
            ],
            { padding: 60, duration: 1500 },
          )
          break

        case 'set_view':
          map.jumpTo({
            center: payload.center,
            zoom: payload.zoom,
            bearing: payload.bearing || 0,
            pitch: payload.pitch || 0,
          })
          break

        // add_marker / add_markers / clear_markers / draw_line / draw_polygon /
        // draw_circle are intercepted in App.tsx and routed through upsertLayer
        // so the data lives in React state and survives reload. MapView no
        // longer handles them directly.

        case 'highlight_features': {
          const { layer_name, property_name, property_value } = payload
          const target = layers.find(
            (l) => l.name.toLowerCase() === layer_name?.toLowerCase(),
          )
          if (!target) break

          const filtered = (target.data.features || []).filter(
            (f: Feature) =>
              String(f.properties?.[property_name]) === String(property_value),
          )
          if (filtered.length === 0) break

          const hlId = 'highlight-temp'
          for (const suffix of ['-fill', '-line', '-circle']) {
            if (map.getLayer(`${hlId}${suffix}`)) map.removeLayer(`${hlId}${suffix}`)
          }
          if (map.getSource(hlId)) map.removeSource(hlId)

          map.addSource(hlId, {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: filtered },
          })
          map.addLayer({
            id: `${hlId}-fill`,
            type: 'fill',
            source: hlId,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Polygon'],
              ['==', ['geometry-type'], 'MultiPolygon'],
            ],
            paint: { 'fill-color': '#ffff00', 'fill-opacity': 0.5 },
          })
          map.addLayer({
            id: `${hlId}-line`,
            type: 'line',
            source: hlId,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Polygon'],
              ['==', ['geometry-type'], 'MultiPolygon'],
              ['==', ['geometry-type'], 'LineString'],
              ['==', ['geometry-type'], 'MultiLineString'],
            ],
            paint: { 'line-color': '#ffff00', 'line-width': 3 },
          })
          map.addLayer({
            id: `${hlId}-circle`,
            type: 'circle',
            source: hlId,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Point'],
              ['==', ['geometry-type'], 'MultiPoint'],
            ],
            paint: {
              'circle-color': '#ffff00',
              'circle-radius': 9,
              'circle-stroke-color': '#000000',
              'circle-stroke-width': 2,
            },
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
            for (const suffix of ['-fill', '-line', '-circle']) {
              if (m.getLayer(`${hlId}${suffix}`)) m.removeLayer(`${hlId}${suffix}`)
            }
            if (m.getSource(hlId)) m.removeSource(hlId)
          }, 10000)
          break
        }

        case 'set_layer_style': {
          // Style changes belong in React state so they survive a project
          // reload. App.tsx persists fillColor/lineColor/opacity onto the
          // layer and the layer-sync effect re-applies on the next render.
          onLayerStyleChangeRef.current?.(payload.layer_name, {
            fillColor: payload.fill_color,
            lineColor: payload.line_color,
            opacity: payload.opacity,
          })
          break
        }

        default:
          break
      }
    }

    onActionsProcessed()
  }, [mapActions, mapReady, layers]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Context menu dismissal (Escape / outside click) ──

  useEffect(() => {
    if (!ctxMenu) return
    const close = () => setCtxMenu(null)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setCtxMenu(null) }
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', onKey)
    }
  }, [ctxMenu])

  // ── Geocoding search ──

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    try {
      // Proxy through the backend — browsers can't set the User-Agent that
      // Nominatim's usage policy requires.
      const resp = await fetch(
        `http://localhost:8765/api/geocode?query=${encodeURIComponent(searchQuery)}&limit=5`,
      )
      const data = await resp.json()
      const results: NominatimSearchResult[] = (data?.results || [])
        .filter((r: { lat: number | null; lon: number | null }) => r.lat != null && r.lon != null)
        .map((r: { display_name: string; lat: number; lon: number }) => ({
          display_name: r.display_name,
          lat: String(r.lat),
          lon: String(r.lon),
        }))
      setSearchResults(results)
    } catch {
      setSearchResults([])
    }
  }

  const flyToResult = (result: NominatimSearchResult) => {
    mapRef.current?.flyTo({
      center: [parseFloat(result.lon), parseFloat(result.lat)],
      zoom: 15,
      duration: 2000,
    })
    setSearchResults([])
    setShowSearch(false)
    setSearchQuery('')
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
              {searchResults.map((r, i) => (
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

      {/* ── Right-click context menu ── */}
      {ctxMenu && (
        <div
          className="map-context-menu"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            className="ctx-item"
            onClick={() => { onAddMarkerRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
          >
            📍 Add marker here
          </button>
          <button
            className="ctx-item"
            onClick={() => { onOpenStreetViewRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
          >
            🛣 Street View
          </button>
          <button
            className="ctx-item"
            onClick={() => { onAskChatRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
          >
            💬 Ask chat about this place
          </button>
        </div>
      )}

    </div>
  )
})

export default MapView
