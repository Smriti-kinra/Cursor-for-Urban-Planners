import { GeoJSONLayer } from '../types'
import './LayerPanel.css'

interface LayerPanelProps {
  layers: GeoJSONLayer[]
  onToggle: (id: string) => void
  onRemove: (id: string) => void
  onZoomTo: (id: string) => void
  onStyle?: (id: string) => void
  activeStyleId?: string | null
  onAttributes?: (id: string) => void
  activeAttrId?: string | null
}

export default function LayerPanel({
  layers,
  onToggle,
  onRemove,
  onZoomTo,
  onStyle,
  activeStyleId,
  onAttributes,
  activeAttrId,
}: LayerPanelProps) {
  if (layers.length === 0) {
    return (
      <div className="layer-panel-empty">
        <p>No layers loaded</p>
        <p className="hint">Click a .geojson file in Files to add a layer</p>
      </div>
    )
  }

  return (
    <div className="layer-panel">
      {layers.map((layer) => (
        <div key={layer.id} className={`layer-item ${!layer.visible ? 'hidden' : ''}`}>
          <button
            className="layer-visibility"
            onClick={() => onToggle(layer.id)}
            title={layer.visible ? 'Hide layer' : 'Show layer'}
          >
            {layer.visible ? '👁' : '⊘'}
          </button>
          <span className="layer-color" style={{ background: layer.color }} />
          <span className="layer-name" title={layer.name}>
            {layer.name}
          </span>
          <span className="layer-count">{layer.data?.features?.length || 0}</span>
          {onAttributes && (
            <button
              className={`layer-style ${activeAttrId === layer.id ? 'active' : ''}`}
              onClick={() => onAttributes(layer.id)}
              title="Edit attributes"
            >
              ✎
            </button>
          )}
          {onStyle && (
            <button
              className={`layer-style ${activeStyleId === layer.id ? 'active' : ''}`}
              onClick={() => onStyle(layer.id)}
              title="Symbology & labels"
            >
              🎨
            </button>
          )}
          <button
            className="layer-zoom"
            onClick={() => onZoomTo(layer.id)}
            title="Zoom to layer"
          >
            ⌖
          </button>
          <button
            className="layer-remove"
            onClick={() => onRemove(layer.id)}
            title="Remove layer"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
