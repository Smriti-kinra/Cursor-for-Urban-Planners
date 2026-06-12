import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from 'react'
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

// Property keys that look like a human-readable title, in preference order.
const POPUP_TITLE_KEYS = ['label', 'name', 'title', 'display_name']
// Internal bookkeeping props that should never surface in a hover popup.
const POPUP_HIDDEN_KEYS = new Set([
  'label', 'name', 'title', 'display_name', 'description',
  'source', 'source_layer', 'fillColor', 'strokeColor',
  'type', 'types',
])

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * Build popup HTML for any feature's properties. Returns '' when there's
 * nothing worth showing. Shared by every layer so AI markers, AI-drawn
 * shapes, and user-drawn shapes all get a hover popup for free.
 */
function popupHtmlForProps(props: Record<string, unknown> | null): string {
  if (!props) return ''
  const titleKey = POPUP_TITLE_KEYS.find((k) => props[k] != null && String(props[k]).trim() !== '')
  const title = titleKey ? String(props[titleKey]).trim() : ''
  const description =
    props.description != null && String(props.description).trim() !== ''
      ? String(props.description).trim()
      : ''
  // Remaining attributes (e.g. zone_code, population) shown as key: value rows.
  const rows = Object.entries(props)
    .filter(([k, v]) => !POPUP_HIDDEN_KEYS.has(k) && v != null && String(v).trim() !== '')
    .slice(0, 8)
    .map(([k, v]) => `<div class="mv-popup-row"><span>${escapeHtml(k)}</span>: ${escapeHtml(v)}</div>`)
    .join('')

  if (!title && !description && !rows) return ''
  return (
    (title ? `<div class="mv-popup-title">${escapeHtml(title)}</div>` : '') +
    (description ? `<div class="mv-popup-desc">${escapeHtml(description)}</div>` : '') +
    rows
  )
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
  /** A user finished drawing a shape. Coordinates are [lng,lat]; for 'point'
   *  the array holds a single pair, for 'line'/'polygon' the full vertex list
   *  (polygon ring is not yet closed). */
  onDrawComplete?: (type: 'point' | 'line' | 'polygon', coordinates: number[][]) => void
}

type DrawMode = 'point' | 'line' | 'polygon' | null

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
    onDrawComplete,
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
  const onDrawCompleteRef = useRef(onDrawComplete)
  onDrawCompleteRef.current = onDrawComplete
  // Drawing state lives in refs so the map event handlers (bound once) always
  // read the current values. drawMode is mirrored to React state for the UI.
  const drawModeRef = useRef<DrawMode>(null)
  const drawVerticesRef = useRef<number[][]>([])
  const ownLayerIds = useRef(new Set<string>())
  const hoverPopupRef = useRef<maplibregl.Popup | null>(null)
  // Per-source revision token: setData() is only called when layer.data changes.
  const layerRevisionRef = useRef(new Map<string, FeatureCollection>())
  const initBasemapRef = useRef(basemap)

  const [mapReady, setMapReady] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<NominatimSearchResult[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [showBasemaps, setShowBasemaps] = useState(false)
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; lng: number; lat: number } | null>(null)
  const [drawMode, setDrawMode] = useState<DrawMode>(null)
  const [drawCount, setDrawCount] = useState(0) // vertices placed in the current draft

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
            'line-width': ['coalesce', ['get', 'lineWidth'], layer.lineWidth ?? 2] as DataDrivenPropertyValueSpecification<number>,
            ...(layer.lineDasharray ? { 'line-dasharray': layer.lineDasharray } : {}),
          },
          layout: { visibility: layer.visible ? 'visible' : 'none' },
        })

        map.addLayer({
          id: `${layer.id}-circle`,
          type: 'circle',
          source: layer.id,
          filter: [
            'all',
            [
              'any',
              ['==', ['geometry-type'], 'Point'],
              ['==', ['geometry-type'], 'MultiPoint'],
            ],
            ['!=', ['get', 'role'], 'label'],
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
          minzoom: labelSpec?.minZoom ?? 10,
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
          map.setPaintProperty(
            `${layer.id}-line`, 'line-width',
            ['coalesce', ['get', 'lineWidth'], layer.lineWidth ?? 2] as DataDrivenPropertyValueSpecification<number>,
          )
          if (layer.lineDasharray) {
            map.setPaintProperty(`${layer.id}-line`, 'line-dasharray', layer.lineDasharray)
          }
        }
        if (map.getLayer(`${layer.id}-circle`)) {
          map.setPaintProperty(`${layer.id}-circle`, 'circle-color', fillColorExpression(layer))
        }
        // Labels: re-apply field/size/color and visibility (gated by enabled +
        // feature cap, AND the layer's own visibility).
        if (map.getLayer(`${layer.id}-label`)) {
          const labelSpec = layer.styleSpec?.label
          map.setLayerZoomRange(`${layer.id}-label`, labelSpec?.minZoom ?? 10, 24)
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

  // ── Drawing tool ──
  //
  // A dedicated `__draw__` source + layers hold the in-progress draft. It is
  // NOT in `layers`, so the layer-sync effect never touches it. On finish the
  // geometry is handed to onDrawComplete, which promotes it to a real layer.

  const DRAW_SRC = '__draw__'

  const redrawDraft = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    const src = map.getSource(DRAW_SRC) as maplibregl.GeoJSONSource | undefined
    if (!src) return
    const verts = drawVerticesRef.current
    const mode = drawModeRef.current
    const features: Feature[] = []
    // Vertices as points.
    for (const v of verts) {
      features.push({ type: 'Feature', geometry: { type: 'Point', coordinates: v }, properties: {} })
    }
    // Draft line / polygon outline.
    if (mode === 'line' && verts.length >= 2) {
      features.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: verts }, properties: {} })
    } else if (mode === 'polygon' && verts.length >= 2) {
      const ring = verts.length >= 3 ? [...verts, verts[0]] : verts
      features.push({
        type: 'Feature',
        geometry: verts.length >= 3
          ? { type: 'Polygon', coordinates: [ring] }
          : { type: 'LineString', coordinates: verts },
        properties: {},
      })
    }
    src.setData({ type: 'FeatureCollection', features })
  }, [])

  const finishDraw = useCallback(() => {
    const mode = drawModeRef.current
    const verts = drawVerticesRef.current
    if (!mode) return
    const min = mode === 'point' ? 1 : mode === 'line' ? 2 : 3
    if (verts.length >= min) {
      onDrawCompleteRef.current?.(mode, verts)
    }
    drawModeRef.current = null
    drawVerticesRef.current = []
    setDrawMode(null)
    setDrawCount(0)
    redrawDraft()
    const map = mapRef.current
    if (map) { map.getCanvas().style.cursor = ''; map.doubleClickZoom.enable() }
  }, [redrawDraft])

  const cancelDraw = useCallback(() => {
    drawModeRef.current = null
    drawVerticesRef.current = []
    setDrawMode(null)
    setDrawCount(0)
    redrawDraft()
    const map = mapRef.current
    if (map) { map.getCanvas().style.cursor = ''; map.doubleClickZoom.enable() }
  }, [redrawDraft])

  const startDraw = useCallback((mode: Exclude<DrawMode, null>) => {
    // Toggle off if the same tool is reselected.
    if (drawModeRef.current === mode) { cancelDraw(); return }
    drawModeRef.current = mode
    drawVerticesRef.current = []
    setDrawMode(mode)
    setDrawCount(0)
    redrawDraft()
    const map = mapRef.current
    if (map) {
      map.getCanvas().style.cursor = 'crosshair'
      // Stop dblclick (used to finish a shape) from also zooming the map.
      map.doubleClickZoom.disable()
    }
  }, [cancelDraw, redrawDraft])

  // Set up the draft source/layers + bind draw event handlers once the map is
  // ready. Handlers read drawMode/vertices from refs, so they never go stale.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    if (!map.getSource(DRAW_SRC)) {
      map.addSource(DRAW_SRC, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({
        id: '__draw__-fill', type: 'fill', source: DRAW_SRC,
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.15 },
      })
      map.addLayer({
        id: '__draw__-line', type: 'line', source: DRAW_SRC,
        filter: ['any', ['==', ['geometry-type'], 'LineString'], ['==', ['geometry-type'], 'Polygon']],
        paint: { 'line-color': '#2563eb', 'line-width': 2, 'line-dasharray': [2, 1] },
      })
      map.addLayer({
        id: '__draw__-vertex', type: 'circle', source: DRAW_SRC,
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-radius': 5, 'circle-color': '#ffffff',
          'circle-stroke-color': '#2563eb', 'circle-stroke-width': 2,
        },
      })
    }

    const onClick = (e: maplibregl.MapMouseEvent) => {
      const mode = drawModeRef.current
      if (!mode) return
      const pt = [e.lngLat.lng, e.lngLat.lat]
      if (mode === 'point') {
        drawVerticesRef.current = [pt]
        finishDraw()
        return
      }
      drawVerticesRef.current = [...drawVerticesRef.current, pt]
      setDrawCount(drawVerticesRef.current.length)
      redrawDraft()
    }
    const onDblClick = (e: maplibregl.MapMouseEvent) => {
      if (!drawModeRef.current || drawModeRef.current === 'point') return
      e.preventDefault()
      finishDraw()
    }

    map.on('click', onClick)
    map.on('dblclick', onDblClick)
    return () => {
      map.off('click', onClick)
      map.off('dblclick', onDblClick)
    }
  }, [mapReady, finishDraw, redrawDraft])

  // ── Hover popups ──
  // Any feature in one of our layers (AI markers, AI-drawn shapes, user-drawn
  // shapes, loaded GeoJSON) shows a popup on hover built from its properties.
  // Bound once; the handler reads the live layer set from ownLayerIds.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    const renderLayerIds = (): string[] => {
      const ids: string[] = []
      for (const baseId of ownLayerIds.current) {
        for (const suffix of ['-fill', '-line', '-circle']) {
          if (map.getLayer(`${baseId}${suffix}`)) ids.push(`${baseId}${suffix}`)
        }
      }
      return ids
    }

    const hidePopup = () => {
      hoverPopupRef.current?.remove()
      hoverPopupRef.current = null
      map.getCanvas().style.cursor = ''
    }

    const onMouseMove = (e: maplibregl.MapMouseEvent) => {
      // Drawing takes over the cursor and clicks; don't fight it.
      if (drawModeRef.current) return hidePopup()
      const ids = renderLayerIds()
      if (!ids.length) return hidePopup()
      const feats = map.queryRenderedFeatures(e.point, { layers: ids })
      const html = feats.length ? popupHtmlForProps(feats[0].properties) : ''
      if (!html) return hidePopup()

      map.getCanvas().style.cursor = 'pointer'
      if (!hoverPopupRef.current) {
        hoverPopupRef.current = new maplibregl.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 12,
          className: 'mv-hover-popup',
        }).addTo(map)
      }
      hoverPopupRef.current.setLngLat(e.lngLat).setHTML(html)
    }

    map.on('mousemove', onMouseMove)
    map.on('mouseout', hidePopup)
    return () => {
      map.off('mousemove', onMouseMove)
      map.off('mouseout', hidePopup)
      hidePopup()
    }
  }, [mapReady])

  // Keyboard: Enter finishes, Escape cancels, Backspace removes last vertex.
  useEffect(() => {
    if (!drawMode) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') { e.preventDefault(); finishDraw() }
      else if (e.key === 'Escape') { e.preventDefault(); cancelDraw() }
      else if (e.key === 'Backspace') {
        e.preventDefault()
        drawVerticesRef.current = drawVerticesRef.current.slice(0, -1)
        setDrawCount(drawVerticesRef.current.length)
        redrawDraft()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawMode, finishDraw, cancelDraw, redrawDraft])

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

        <div className="toolbar-divider" />

        <button
          className={`toolbar-btn ${drawMode === 'point' ? 'active' : ''}`}
          onClick={() => startDraw('point')}
          title="Draw point"
        >
          📍
        </button>
        <button
          className={`toolbar-btn ${drawMode === 'line' ? 'active' : ''}`}
          onClick={() => startDraw('line')}
          title="Draw line"
        >
          ╱
        </button>
        <button
          className={`toolbar-btn ${drawMode === 'polygon' ? 'active' : ''}`}
          onClick={() => startDraw('polygon')}
          title="Draw polygon"
        >
          ⬠
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

      {/* ── Draw helper bar ── */}
      {drawMode && (
        <div className="draw-bar">
          <span className="draw-hint">
            {drawMode === 'point'
              ? 'Click the map to place a point.'
              : `Click to add vertices (${drawCount}). Double-click or Enter to finish, Esc to cancel.`}
          </span>
          {drawMode !== 'point' && (
            <button
              className="draw-finish"
              onClick={finishDraw}
              disabled={drawCount < (drawMode === 'line' ? 2 : 3)}
            >
              Finish
            </button>
          )}
          <button className="draw-cancel" onClick={cancelDraw}>Cancel</button>
        </div>
      )}

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
