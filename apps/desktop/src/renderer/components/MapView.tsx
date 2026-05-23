import { useEffect, useRef, useState, forwardRef, useImperativeHandle } from 'react'
import maplibregl from 'maplibre-gl'
import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import * as turf from '@turf/turf'
import type { Feature } from 'geojson'
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

interface MapViewProps {
  layers: GeoJSONLayer[]
  basemap: string
  initialState: MapViewState
  mapActions: MapAction[]
  onMapMove: (state: MapViewState) => void
  onBoundsChange?: (b: { west: number; south: number; east: number; north: number }) => void
  onBasemapChange: (basemap: string) => void
  onActionsProcessed: () => void
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
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const onBoundsChangeRef = useRef(onBoundsChange)
  onBoundsChangeRef.current = onBoundsChange
  const ownLayerIds = useRef(new Set<string>())
  const initBasemapRef = useRef(basemap)
  const aiMarkersRef = useRef<maplibregl.Marker[]>([])
  const aiShapeCounterRef = useRef(0)
  const aiShapeIdsRef = useRef<Set<string>>(new Set())

  const [mapReady, setMapReady] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<NominatimSearchResult[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [showBasemaps, setShowBasemaps] = useState(false)

  // ── Initialize map ──

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const { tiles, attribution } = BASEMAPS[initBasemapRef.current] || BASEMAPS.street

    console.log('[MapView] Creating map with basemap:', initBasemapRef.current)

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
      const b = map.getBounds()
      onBoundsChangeRef.current?.({
        west: b.getWest(),
        south: b.getSouth(),
        east: b.getEast(),
        north: b.getNorth(),
      })
    })

    mapRef.current = map

    map.on('load', () => {
      console.log('[MapView] Map loaded. Style layers:', map.getStyle().layers.map((l) => l.id))

      setMapReady(true)
    })

    return () => {
      setMapReady(false)
      for (const m of aiMarkersRef.current) m.remove()
      aiMarkersRef.current = []
      map.remove()
      mapRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sync GeoJSON layers ──

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    console.log('[MapView] syncLayers running, count:', layers.length)

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
        console.log('[MapView] Adding layer source:', layer.id, layer.name)
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
          paint: {
            'fill-color': ['coalesce', ['get', 'fillColor'], layer.color] as DataDrivenPropertyValueSpecification<string>,
            'fill-opacity': ['coalesce', ['get', 'fillOpacity'], 0.3] as DataDrivenPropertyValueSpecification<number>,
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
            'line-color': ['coalesce', ['get', 'strokeColor'], layer.color] as DataDrivenPropertyValueSpecification<string>,
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
            'line-color': ['coalesce', ['get', 'strokeColor'], layer.color] as DataDrivenPropertyValueSpecification<string>,
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
            'circle-color': layer.color,
            'circle-radius': 6,
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 1.5,
          },
          layout: { visibility: layer.visible ? 'visible' : 'none' },
        })

        console.log('[MapView] Layer added. All layers now:', map.getStyle().layers.map((l) => l.id))

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
  }, [layers, mapReady])

  // ── Basemap switching ──

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    if (basemap === initBasemapRef.current && map.getSource('basemap')) return

    console.log('[MapView] Switching basemap to:', basemap)

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
    console.log('[MapView] Basemap switched. Layers:', map.getStyle().layers.map((l) => l.id))
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

        case 'add_marker': {
          const el = document.createElement('div')
          el.style.cssText = `width:14px;height:14px;border-radius:50%;background:${payload.color || '#e6194b'};border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.4);cursor:pointer;`
          const marker = new maplibregl.Marker({ element: el })
            .setLngLat([payload.lng, payload.lat])
            .setPopup(
              new maplibregl.Popup({ offset: 10 }).setHTML(
                `<div style="font:13px/1.4 system-ui;max-width:200px"><b>${payload.label || ''}</b></div>`,
              ),
            )
            .addTo(map)
          aiMarkersRef.current.push(marker)
          break
        }

        case 'add_markers': {
          for (const m of payload.markers || []) {
            const el = document.createElement('div')
            el.style.cssText = `width:12px;height:12px;border-radius:50%;background:${m.color || '#e6194b'};border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.4);cursor:pointer;`
            const marker = new maplibregl.Marker({ element: el })
              .setLngLat([m.lng, m.lat])
              .setPopup(
                new maplibregl.Popup({ offset: 10 }).setHTML(
                  `<div style="font:13px/1.4 system-ui;max-width:200px"><b>${m.label || ''}</b></div>`,
                ),
              )
              .addTo(map)
            aiMarkersRef.current.push(marker)
          }
          break
        }

        case 'clear_markers':
          for (const m of aiMarkersRef.current) m.remove()
          aiMarkersRef.current = []
          break

        case 'draw_line': {
          const lineId = `ai-line-${aiShapeCounterRef.current++}`
          map.addSource(lineId, {
            type: 'geojson',
            data: {
              type: 'Feature',
              geometry: { type: 'LineString', coordinates: payload.coordinates },
              properties: { label: payload.label || '' },
            },
          })
          map.addLayer({
            id: lineId,
            type: 'line',
            source: lineId,
            paint: {
              'line-color': payload.color || '#ef4444',
              'line-width': payload.width || 3,
            },
          })
          aiShapeIdsRef.current.add(lineId)
          break
        }

        case 'draw_polygon': {
          const polyId = `ai-poly-${aiShapeCounterRef.current++}`
          const rawCoords = payload.coordinates || []
          const ring =
            rawCoords.length >= 3 &&
            (rawCoords[0][0] !== rawCoords[rawCoords.length - 1][0] ||
              rawCoords[0][1] !== rawCoords[rawCoords.length - 1][1])
              ? [...rawCoords, rawCoords[0]]
              : rawCoords
          map.addSource(polyId, {
            type: 'geojson',
            data: {
              type: 'Feature',
              geometry: { type: 'Polygon', coordinates: [ring] },
              properties: { label: payload.label || '' },
            },
          })
          map.addLayer({
            id: `${polyId}-fill`,
            type: 'fill',
            source: polyId,
            paint: {
              'fill-color': payload.color || '#3b82f6',
              'fill-opacity': payload.opacity ?? 0.3,
            },
          })
          map.addLayer({
            id: `${polyId}-outline`,
            type: 'line',
            source: polyId,
            paint: { 'line-color': payload.color || '#3b82f6', 'line-width': 2 },
          })
          aiShapeIdsRef.current.add(polyId)
          aiShapeIdsRef.current.add(`${polyId}-fill`)
          aiShapeIdsRef.current.add(`${polyId}-outline`)
          break
        }

        case 'draw_circle': {
          const circleId = `ai-circle-${aiShapeCounterRef.current++}`
          const circle = turf.circle(
            [payload.center_lng, payload.center_lat],
            payload.radius_km,
            { units: 'kilometers', steps: 64 },
          )
          map.addSource(circleId, { type: 'geojson', data: circle })
          map.addLayer({
            id: `${circleId}-fill`,
            type: 'fill',
            source: circleId,
            paint: {
              'fill-color': payload.color || '#8b5cf6',
              'fill-opacity': 0.2,
            },
          })
          map.addLayer({
            id: `${circleId}-outline`,
            type: 'line',
            source: circleId,
            paint: {
              'line-color': payload.color || '#8b5cf6',
              'line-width': 2,
              'line-dasharray': [4, 2],
            },
          })
          aiShapeIdsRef.current.add(circleId)
          aiShapeIdsRef.current.add(`${circleId}-fill`)
          aiShapeIdsRef.current.add(`${circleId}-outline`)
          break
        }

        case 'highlight_features': {
          const { layer_name, property_name, property_value } = payload
          const target = layers.find(
            (l) => l.name.toLowerCase() === layer_name?.toLowerCase(),
          )
          if (target) {
            const filtered = (target.data.features || []).filter(
              (f: Feature) =>
                String(f.properties?.[property_name]) === String(property_value),
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
          break
        }

        case 'set_layer_style': {
          const { layer_name, fill_color, line_color, opacity } = payload
          const target = layers.find(
            (l) => l.name.toLowerCase() === layer_name?.toLowerCase(),
          )
          if (target) {
            const lid = target.id
            if (fill_color && map.getLayer(`${lid}-fill`))
              map.setPaintProperty(`${lid}-fill`, 'fill-color', fill_color)
            if (opacity !== undefined && map.getLayer(`${lid}-fill`))
              map.setPaintProperty(`${lid}-fill`, 'fill-opacity', opacity)
            if ((line_color || fill_color) && map.getLayer(`${lid}-outline`))
              map.setPaintProperty(
                `${lid}-outline`,
                'line-color',
                line_color || fill_color,
              )
            if ((line_color || fill_color) && map.getLayer(`${lid}-line`))
              map.setPaintProperty(
                `${lid}-line`,
                'line-color',
                line_color || fill_color,
              )
          }
          break
        }

        default:
          break
      }
    }

    onActionsProcessed()
  }, [mapActions, mapReady, layers]) // eslint-disable-line react-hooks/exhaustive-deps

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

    </div>
  )
})

export default MapView
