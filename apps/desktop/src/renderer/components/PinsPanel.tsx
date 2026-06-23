import { useMemo } from 'react'
import type { FeatureCollection } from 'geojson'
import { GeoJSONLayer } from '../types'
import './PinsPanel.css'

interface PinsPanelProps {
  layer: GeoJSONLayer | null
  onChange: (layerId: string, data: FeatureCollection) => void
  onZoomToPin: (lng: number, lat: number) => void
}

export default function PinsPanel({ layer, onChange, onZoomToPin }: PinsPanelProps) {
  const features = useMemo(() => layer?.data?.features || [], [layer])

  const setLabel = (idx: number, value: string) => {
    if (!layer) return
    const updatedFeatures = features.map((f, i) =>
      i === idx ? { ...f, properties: { ...(f.properties || {}), label: value } } : f
    )
    onChange(layer.id, { type: 'FeatureCollection', features: updatedFeatures })
  }

  const deletePin = (idx: number) => {
    if (!layer) return
    const updatedFeatures = features.filter((_, i) => i !== idx)
    onChange(layer.id, { type: 'FeatureCollection', features: updatedFeatures })
  }

  return (
    <div className="pins-panel">
      <div className="pins-header">
        <span className="pins-title">AI & Map Pins</span>
      </div>
      {features.length === 0 ? (
        <div className="pins-empty">
          <p>No pins placed yet.</p>
          <p className="hint">Right-click on the map to add a pin, or ask the AI to drop markers in the chat.</p>
        </div>
      ) : (
        <div className="pins-list-container">
          <div className="pins-list">
            {features.map((f, idx) => {
              const coords = f.geometry && 'coordinates' in f.geometry ? f.geometry.coordinates : null
              const [lng, lat] = Array.isArray(coords) ? coords : [0, 0]
              const label = f.properties?.label ?? ''
              return (
                <div key={idx} className="pin-item">
                  <div className="pin-row">
                    <input
                      type="text"
                      className="pin-label-input"
                      value={label}
                      onChange={(e) => setLabel(idx, e.target.value)}
                      placeholder={`${lat.toFixed(5)}, ${lng.toFixed(5)}`}
                    />
                    <div className="pin-actions">
                      <button
                        type="button"
                        className="pin-action-btn pin-zoom"
                        onClick={() => onZoomToPin(lng, lat)}
                        title="Zoom to pin"
                      >
                        ⌖
                      </button>
                      <button
                        type="button"
                        className="pin-action-btn pin-delete"
                        onClick={() => deletePin(idx)}
                        title="Delete pin"
                      >
                        🗑
                      </button>
                    </div>
                  </div>
                  <div className="pin-coords">
                    {lat.toFixed(6)}, {lng.toFixed(6)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
