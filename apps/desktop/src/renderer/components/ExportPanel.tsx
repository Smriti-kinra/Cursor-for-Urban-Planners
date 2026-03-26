import { GeoJSONLayer } from '../types'
import './ExportPanel.css'

interface ExportPanelProps {
  layers: GeoJSONLayer[]
  workspacePath: string | null
  onExportMapPng: () => void
  onExportLayer: (layerId: string) => void
  onExportPdf: () => void
  onExportClippedRegion: (name: string) => void
}

export default function ExportPanel({
  layers,
  workspacePath,
  onExportMapPng,
  onExportLayer,
  onExportPdf,
  onExportClippedRegion,
}: ExportPanelProps) {
  const handleClipSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = e.currentTarget
    const input = form.elements.namedItem('clipname') as HTMLInputElement
    const name = input?.value?.trim() || 'clipped-region'
    onExportClippedRegion(name)
    input.value = ''
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
    </div>
  )
}
