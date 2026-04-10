import { useState } from 'react'
import { DrawStyleConfig, ZonePreset } from '../types'
import './DrawToolbar.css'

interface DrawToolbarProps {
  drawStyle: DrawStyleConfig
  onDrawStyleChange: (s: Partial<DrawStyleConfig>) => void
  drawMode: string | null
  activeZonePreset: ZonePreset | null
  onZonePresetChange: (z: ZonePreset | null) => void
  zonePresets: ZonePreset[]
  onUndo: () => void
  onRedo: () => void
  canUndo: boolean
  canRedo: boolean
  /** ID of the currently selected TerraDraw feature (null if none). */
  selectedFeatureId: string | null
  onApplyStyleToSelected: (style: { fillColor: string; strokeColor: string }) => void
  /** Current text annotation style. */
  textStyle: { color: string; fontSize: number }
  onTextStyleChange: (s: Partial<{ color: string; fontSize: number }>) => void
}

export default function DrawToolbar({
  drawStyle,
  onDrawStyleChange,
  drawMode,
  activeZonePreset,
  onZonePresetChange,
  zonePresets,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  selectedFeatureId,
  onApplyStyleToSelected,
  textStyle,
  onTextStyleChange,
}: DrawToolbarProps) {
  const [selFill, setSelFill] = useState(drawStyle.fillColor)
  const [selStroke, setSelStroke] = useState(drawStyle.strokeColor)

  const isTextMode = drawMode === 'text'
  const hasSelection = !!selectedFeatureId

  return (
    <div className="draw-toolbar">
      {/* ── Global draw style ── */}
      {!isTextMode && (
        <div className="draw-toolbar-row">
          <label className="draw-toolbar-label">
            Fill
            <input
              type="color"
              value={drawStyle.fillColor}
              onChange={(e) => onDrawStyleChange({ fillColor: e.target.value })}
              title="Fill color (new shapes)"
            />
          </label>
          <label className="draw-toolbar-label">
            Stroke
            <input
              type="color"
              value={drawStyle.strokeColor}
              onChange={(e) => onDrawStyleChange({ strokeColor: e.target.value })}
              title="Stroke color (new shapes)"
            />
          </label>
          <label className="draw-toolbar-label flex">
            Opacity
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={drawStyle.fillOpacity}
              onChange={(e) => onDrawStyleChange({ fillOpacity: parseFloat(e.target.value) })}
            />
          </label>
          <label className="draw-toolbar-label flex">
            Width
            <input
              type="range"
              min={1}
              max={12}
              step={1}
              value={drawStyle.lineWidth}
              onChange={(e) => onDrawStyleChange({ lineWidth: parseInt(e.target.value, 10) })}
            />
          </label>
          <select
            className="draw-toolbar-select"
            value={drawStyle.lineDash}
            onChange={(e) =>
              onDrawStyleChange({ lineDash: e.target.value as DrawStyleConfig['lineDash'] })
            }
            title="Line style"
          >
            <option value="solid">Solid</option>
            <option value="dashed">Dashed</option>
            <option value="dotted">Dotted</option>
          </select>
        </div>
      )}

      {/* ── Text mode controls ── */}
      {isTextMode && (
        <div className="draw-toolbar-row">
          <label className="draw-toolbar-label">
            Color
            <input
              type="color"
              value={textStyle.color}
              onChange={(e) => onTextStyleChange({ color: e.target.value })}
              title="Text color"
            />
          </label>
          <label className="draw-toolbar-label flex">
            Size
            <input
              type="range"
              min={8}
              max={36}
              step={1}
              value={textStyle.fontSize}
              onChange={(e) => onTextStyleChange({ fontSize: parseInt(e.target.value, 10) })}
            />
            <span className="draw-toolbar-value">{textStyle.fontSize}px</span>
          </label>
          <span className="draw-toolbar-hint">Click map to place text · Right-click to remove</span>
        </div>
      )}

      {/* ── Per-feature style override (shown when a feature is selected) ── */}
      {hasSelection && !isTextMode && (
        <div className="draw-toolbar-row draw-toolbar-selection">
          <span className="draw-toolbar-hint">Selected feature:</span>
          <label className="draw-toolbar-label">
            Fill
            <input
              type="color"
              value={selFill}
              onChange={(e) => setSelFill(e.target.value)}
              title="Override fill color for selected feature"
            />
          </label>
          <label className="draw-toolbar-label">
            Stroke
            <input
              type="color"
              value={selStroke}
              onChange={(e) => setSelStroke(e.target.value)}
              title="Override stroke color for selected feature"
            />
          </label>
          <button
            type="button"
            className="toolbar-mini"
            onClick={() => onApplyStyleToSelected({ fillColor: selFill, strokeColor: selStroke })}
            title="Apply these colors to the selected feature"
          >
            Apply
          </button>
        </div>
      )}

      {/* ── History ── */}
      <div className="draw-toolbar-row">
        <button
          type="button"
          className="toolbar-mini"
          onClick={onUndo}
          disabled={!canUndo}
          title="Undo drawing"
        >
          Undo
        </button>
        <button
          type="button"
          className="toolbar-mini"
          onClick={onRedo}
          disabled={!canRedo}
          title="Redo drawing"
        >
          Redo
        </button>
      </div>

      {/* ── Zoning presets ── */}
      {!isTextMode && (
        <div className="draw-toolbar-zoning">
          <span className="draw-toolbar-zoning-title">Zoning tag (new shapes)</span>
          <div className="zone-chips">
            <button
              type="button"
              className={`zone-chip ${activeZonePreset === null ? 'active' : ''}`}
              onClick={() => onZonePresetChange(null)}
            >
              None
            </button>
            {zonePresets.map((z) => (
              <button
                key={z.code}
                type="button"
                className={`zone-chip ${activeZonePreset?.code === z.code ? 'active' : ''}`}
                style={{ borderLeft: `4px solid ${z.color}` }}
                title={z.description}
                onClick={() => onZonePresetChange(z)}
              >
                {z.code}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
