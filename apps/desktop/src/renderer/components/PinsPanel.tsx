import { useState, useMemo, useEffect } from 'react'
import type { FeatureCollection } from 'geojson'
import { GeoJSONLayer } from '../types'
import './PinsPanel.css'

interface MarkerInput {
  lat: number
  lng: number
  label?: string
  color?: string
  description?: string
}

interface PinsPanelProps {
  layer: GeoJSONLayer | null
  onChange: (layerId: string, data: FeatureCollection) => void
  onZoomToPin: (lng: number, lat: number) => void
  onAddPin: (markers: MarkerInput[]) => void
}

const PIN_COLORS = [
  { name: 'Blue', value: '#89b4fa' },
  { name: 'Red', value: '#f38ba8' },
  { name: 'Green', value: '#a6e3a1' },
  { name: 'Yellow', value: '#f9e2af' },
  { name: 'Orange', value: '#fab387' },
  { name: 'Lavender', value: '#b4befe' },
  { name: 'Mauve', value: '#cba6f7' },
  { name: 'Pink', value: '#f5c2e7' },
]

export default function PinsPanel({ layer, onChange, onZoomToPin, onAddPin }: PinsPanelProps) {
  const features = useMemo(() => layer?.data?.features || [], [layer])

  // Form state for manual pin addition
  const [showAddForm, setShowAddForm] = useState(false)
  const [newLat, setNewLat] = useState('')
  const [newLng, setNewLng] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newColor, setNewColor] = useState('#89b4fa')

  // Active color picker index
  const [activeColorPickerIdx, setActiveColorPickerIdx] = useState<number | null>(null)

  useEffect(() => {
    const closePicker = () => setActiveColorPickerIdx(null)
    window.addEventListener('click', closePicker)
    return () => window.removeEventListener('click', closePicker)
  }, [])

  const setLabel = (idx: number, value: string) => {
    if (!layer) return
    const updatedFeatures = features.map((f, i) =>
      i === idx ? { ...f, properties: { ...(f.properties || {}), label: value } } : f
    )
    onChange(layer.id, { type: 'FeatureCollection', features: updatedFeatures })
  }

  const setDescription = (idx: number, value: string) => {
    if (!layer) return
    const updatedFeatures = features.map((f, i) =>
      i === idx ? { ...f, properties: { ...(f.properties || {}), description: value } } : f
    )
    onChange(layer.id, { type: 'FeatureCollection', features: updatedFeatures })
  }

  const setColor = (idx: number, colorVal: string) => {
    if (!layer) return
    const updatedFeatures = features.map((f, i) =>
      i === idx
        ? {
            ...f,
            properties: {
              ...(f.properties || {}),
              fillColor: colorVal,
              strokeColor: colorVal,
            },
          }
        : f
    )
    onChange(layer.id, { type: 'FeatureCollection', features: updatedFeatures })
  }

  const deletePin = (idx: number) => {
    if (!layer) return
    const updatedFeatures = features.filter((_, i) => i !== idx)
    onChange(layer.id, { type: 'FeatureCollection', features: updatedFeatures })
  }

  const handleAddPinSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const lat = parseFloat(newLat)
    const lng = parseFloat(newLng)
    if (isNaN(lat) || lat < -90 || lat > 90) {
      alert('Please enter a valid latitude (-90 to 90)')
      return
    }
    if (isNaN(lng) || lng < -180 || lng > 180) {
      alert('Please enter a valid longitude (-180 to 180)')
      return
    }
    if (!newLabel.trim()) {
      alert('Please enter a label for the pin')
      return
    }

    onAddPin([
      {
        lat,
        lng,
        label: newLabel.trim(),
        color: newColor,
        description: newDesc.trim() || undefined,
      },
    ])

    // Reset form
    setNewLat('')
    setNewLng('')
    setNewLabel('')
    setNewDesc('')
    setShowAddForm(false)
  }

  return (
    <div className="pins-panel">
      <div className="pins-header">
        <span className="pins-title">AI & Map Pins</span>
        <button
          className={`pins-add-toggle-btn ${showAddForm ? 'active' : ''}`}
          onClick={() => setShowAddForm(!showAddForm)}
          title="Add Pin Manually"
        >
          {showAddForm ? '✕ Close' : '＋ Add Pin'}
        </button>
      </div>

      {showAddForm && (
        <form className="pins-add-form animate-slide" onSubmit={handleAddPinSubmit}>
          <div className="form-group-row">
            <div className="form-group">
              <label>Latitude</label>
              <input
                type="number"
                step="any"
                required
                placeholder="e.g. 30.7333"
                value={newLat}
                onChange={(e) => setNewLat(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>Longitude</label>
              <input
                type="number"
                step="any"
                required
                placeholder="e.g. 76.7794"
                value={newLng}
                onChange={(e) => setNewLng(e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <label>Label</label>
            <input
              type="text"
              required
              placeholder="Pin title or name"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label>Description (Optional)</label>
            <textarea
              rows={2}
              placeholder="Notes or details about this location"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label>Color</label>
            <div className="color-dots-selector">
              {PIN_COLORS.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  className={`color-dot-option ${newColor === c.value ? 'selected' : ''}`}
                  style={{ backgroundColor: c.value }}
                  onClick={() => setNewColor(c.value)}
                  title={c.name}
                />
              ))}
            </div>
          </div>

          <button type="submit" className="pins-add-submit-btn">
            Create Pin
          </button>
        </form>
      )}

      {features.length === 0 ? (
        <div className="pins-empty">
          <p>No pins placed yet.</p>
          <p className="hint">
            Right-click on the map to add a pin, ask the AI to drop markers in the chat, or click the &quot;Add Pin&quot; button above.
          </p>
        </div>
      ) : (
        <div className="pins-list-container">
          <div className="pins-list">
            {features.map((f, idx) => {
              const coords = f.geometry && 'coordinates' in f.geometry ? f.geometry.coordinates : null
              const [lng, lat] = Array.isArray(coords) ? coords : [0, 0]
              const label = f.properties?.label ?? ''
              const description = f.properties?.description ?? ''
              
              // Get current color or default to first theme color (blue)
              const currentColor = f.properties?.fillColor ?? '#89b4fa'

              return (
                <div key={idx} className="pin-card-item">
                  <div className="pin-card-row">
                    <div className="pin-color-picker-wrap">
                      <button
                        type="button"
                        className="pin-color-indicator"
                        style={{ backgroundColor: currentColor }}
                        onClick={(e) => toggleColorPicker(idx, e)}
                        title="Change Color"
                      />
                      {activeColorPickerIdx === idx && (
                        <div className="pin-color-dropdown" onClick={(e) => e.stopPropagation()}>
                          {PIN_COLORS.map((c) => (
                            <button
                              key={c.value}
                              type="button"
                              className="color-dropdown-option"
                              style={{ backgroundColor: c.value }}
                              onClick={() => {
                                setColor(idx, c.value)
                                setActiveColorPickerIdx(null)
                              }}
                              title={c.name}
                            />
                          ))}
                        </div>
                      )}
                    </div>

                    <input
                      type="text"
                      className="pin-card-label-input"
                      value={label}
                      onChange={(e) => setLabel(idx, e.target.value)}
                      placeholder="Enter pin label..."
                    />

                    <div className="pin-card-actions">
                      <button
                        type="button"
                        className="pin-card-btn pin-zoom"
                        onClick={() => onZoomToPin(lng, lat)}
                        title="Zoom to pin"
                      >
                        ⌖
                      </button>
                      <button
                        type="button"
                        className="pin-card-btn pin-delete"
                        onClick={() => deletePin(idx)}
                        title="Delete pin"
                      >
                        🗑
                      </button>
                    </div>
                  </div>

                  <div className="pin-card-coords">
                    {lat.toFixed(6)}, {lng.toFixed(6)}
                  </div>

                  <textarea
                    className="pin-card-desc-textarea"
                    value={description}
                    onChange={(e) => setDescription(idx, e.target.value)}
                    placeholder="Add details or notes about this pin..."
                    rows={1}
                  />
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
