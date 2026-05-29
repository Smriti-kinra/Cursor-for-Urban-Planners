import { useState } from 'react'
import type { Polygon, MultiPolygon } from 'geojson'
import { GeoJSONLayer, BoundaryGeometry } from '../types'
import './ExportPanel.css'

interface NominatimResult {
  display_name: string
  geojson: Polygon | MultiPolygon | { type: string }
  osm_type: string
  type: string
}

interface ExportPanelProps {
  layers: GeoJSONLayer[]
  workspacePath: string | null
  onExportMapPng: () => void
  onExportLayer: (layerId: string) => void
  onExportPdf: () => void
  onExportClippedRegion: (name: string) => void
  onPreviewBoundary: (geom: BoundaryGeometry | null) => void
  onSaveByRegion: (displayName: string, boundaryGeom: BoundaryGeometry) => void
  onSavePngToArtifact: (title: string) => void
  onSavePdfToArtifact: (title: string) => void
  onSuggestExportTitle: () => string
}

export default function ExportPanel({
  layers,
  workspacePath,
  onExportMapPng,
  onExportLayer,
  onExportPdf,
  onExportClippedRegion,
  onPreviewBoundary,
  onSaveByRegion,
  onSavePngToArtifact,
  onSavePdfToArtifact,
  onSuggestExportTitle,
}: ExportPanelProps) {
  const [regionQuery, setRegionQuery] = useState('')
  const [artifactTitle, setArtifactTitle] = useState('')
  const [regionResults, setRegionResults] = useState<NominatimResult[]>([])
  const [selectedRegion, setSelectedRegion] = useState<NominatimResult | null>(null)
  const [regionSearching, setRegionSearching] = useState(false)

  const handleClipSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = e.currentTarget
    const input = form.elements.namedItem('clipname') as HTMLInputElement
    const name = input?.value?.trim() || 'clipped-region'
    onExportClippedRegion(name)
    input.value = ''
  }

  const searchRegion = async () => {
    if (!regionQuery.trim()) return
    setRegionSearching(true)
    setRegionResults([])
    setSelectedRegion(null)
    onPreviewBoundary(null)
    try {
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(regionQuery)}&format=json&polygon_geojson=1&limit=6`,
        { headers: { 'User-Agent': 'CursorUrbanPlanners/1.0' } },
      )
      const data: NominatimResult[] = await resp.json()
      // Only keep results that have a polygon boundary
      const polygons = data.filter(
        (r) => r.geojson && ['Polygon', 'MultiPolygon'].includes(r.geojson.type),
      )
      setRegionResults(polygons)
    } catch {
      setRegionResults([])
    } finally {
      setRegionSearching(false)
    }
  }

  const selectRegion = (r: NominatimResult) => {
    setSelectedRegion(r)
    if (r.geojson.type === 'Polygon' || r.geojson.type === 'MultiPolygon') {
      onPreviewBoundary(r.geojson as BoundaryGeometry)
    }
  }

  const clearRegion = () => {
    setSelectedRegion(null)
    setRegionResults([])
    setRegionQuery('')
    onPreviewBoundary(null)
  }

  return (
    <div className="export-panel">
      <p className="export-hint">
        Export map or layer data. PNG captures the current map view. GeoJSON uses your workspace folder when open.
      </p>
      <div className="export-actions">
        <button type="button" className="export-btn primary" onClick={onExportMapPng}>
          Save map as PNG
        </button>
        <button type="button" className="export-btn" onClick={onExportPdf}>
          Map + title as PDF
        </button>
      </div>

      <h4 className="export-sub">Save to artifacts</h4>
      <div className="export-artifact-save">
        <input
          type="text"
          className="export-input"
          placeholder="Artifact title"
          value={artifactTitle}
          onChange={(e) => setArtifactTitle(e.target.value)}
        />
        <button
          type="button"
          className="export-btn small"
          onClick={() => setArtifactTitle(onSuggestExportTitle())}
        >
          Suggest name
        </button>
        <div className="export-artifact-btns">
          <button
            type="button"
            className="export-btn primary"
            disabled={!artifactTitle.trim()}
            onClick={() => onSavePngToArtifact(artifactTitle.trim())}
          >
            Save PNG to artifacts
          </button>
          <button
            type="button"
            className="export-btn"
            disabled={!artifactTitle.trim()}
            onClick={() => onSavePdfToArtifact(artifactTitle.trim())}
          >
            Save PDF to artifacts
          </button>
        </div>
      </div>

      <h4 className="export-sub">Layers as GeoJSON</h4>
      {layers.length === 0 ? (
        <p className="export-empty">No layers to export.</p>
      ) : (
        <ul className="export-layer-list">
          {layers.map((l) => (
            <li key={l.id}>
              <span className="export-layer-name">{l.name}</span>
              <button type="button" className="export-btn small" onClick={() => onExportLayer(l.id)}>
                Download .geojson
              </button>
            </li>
          ))}
        </ul>
      )}

      <h4 className="export-sub">Clip to current map extent</h4>
      <form className="export-clip-form" onSubmit={handleClipSubmit}>
        <input
          name="clipname"
          type="text"
          placeholder="output base name"
          className="export-input"
          disabled={!workspacePath || layers.length === 0}
        />
        <button
          type="submit"
          className="export-btn"
          disabled={!workspacePath || layers.length === 0}
          title="Clip all layers to visible bounds and save into workspace"
        >
          Save clipped GeoJSON
        </button>
      </form>
      {!workspacePath && (
        <p className="export-warn">Open a workspace folder to save clipped files.</p>
      )}

      {/* ── Save by admin boundary ── */}
      <h4 className="export-sub">Save by region / boundary</h4>
      <p className="export-hint">
        Search for a district, city, or province — fetches its boundary from OSM and clips all layers to it.
      </p>
      <div className="export-region-search">
        <input
          type="text"
          className="export-input"
          placeholder="e.g. Mumbai, Delhi, Manhattan"
          value={regionQuery}
          onChange={(e) => setRegionQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && searchRegion()}
        />
        <button
          type="button"
          className="export-btn"
          onClick={searchRegion}
          disabled={regionSearching || !regionQuery.trim()}
        >
          {regionSearching ? '...' : 'Search'}
        </button>
      </div>

      {regionResults.length > 0 && !selectedRegion && (
        <ul className="export-region-results">
          {regionResults.map((r, i) => (
            <li key={i}>
              <button
                type="button"
                className="export-region-result-btn"
                onClick={() => selectRegion(r)}
                title={`${r.type} · ${r.osm_type}`}
              >
                {r.display_name.slice(0, 70)}{r.display_name.length > 70 ? '…' : ''}
              </button>
            </li>
          ))}
        </ul>
      )}

      {regionResults.length > 0 && !selectedRegion && (
        <p className="export-hint">Select a result to preview its boundary on the map.</p>
      )}

      {selectedRegion && (
        <div className="export-region-selected">
          <p className="export-region-name">{selectedRegion.display_name.slice(0, 60)}</p>
          <div className="export-region-actions">
            <button
              type="button"
              className="export-btn primary"
              disabled={!workspacePath || layers.length === 0}
              onClick={() => {
                if (selectedRegion.geojson.type !== 'Polygon' && selectedRegion.geojson.type !== 'MultiPolygon') return
                onSaveByRegion(
                  regionQuery.replace(/[^a-z0-9-_ ]/gi, '').trim() || 'region',
                  selectedRegion.geojson as BoundaryGeometry,
                )
              }}
              title={!workspacePath ? 'Open a workspace first' : 'Clip all layers to this boundary and save'}
            >
              Save within this region
            </button>
            <button
              type="button"
              className="export-btn"
              onClick={clearRegion}
            >
              Clear
            </button>
          </div>
          {!workspacePath && (
            <p className="export-warn">Open a workspace folder to save.</p>
          )}
          {layers.length === 0 && (
            <p className="export-warn">Load at least one layer to clip.</p>
          )}
        </div>
      )}
    </div>
  )
}
