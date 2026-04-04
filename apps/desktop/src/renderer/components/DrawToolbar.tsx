import { DrawStyleConfig, ZonePreset } from '../types'
import './DrawToolbar.css'

interface DrawToolbarProps {
  drawStyle: DrawStyleConfig
  onDrawStyleChange: (s: Partial<DrawStyleConfig>) => void
  activeZonePreset: ZonePreset | null
  onZonePresetChange: (z: ZonePreset | null) => void
  zonePresets: ZonePreset[]
  onUndo: () => void
  onRedo: () => void
  canUndo: boolean
  canRedo: boolean
  /** False until a workspace folder is open (same as map drawing). */
  enabled?: boolean
}

export default function DrawToolbar({
  drawStyle,
  onDrawStyleChange,
  activeZonePreset,
  onZonePresetChange,
  zonePresets,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  enabled = true,
}: DrawToolbarProps) {
  return (
    <div className={`draw-toolbar${enabled ? '' : ' draw-toolbar-disabled'}`} aria-disabled={!enabled}>
      <div className="draw-toolbar-row">
        <label className="draw-toolbar-label">
          Fill
          <input
            type="color"
            value={drawStyle.fillColor}
            disabled={!enabled}
            onChange={(e) => onDrawStyleChange({ fillColor: e.target.value })}
            title="Fill color"
          />
        </label>
        <label className="draw-toolbar-label">
          Stroke
          <input
            type="color"
            value={drawStyle.strokeColor}
            disabled={!enabled}
            onChange={(e) => onDrawStyleChange({ strokeColor: e.target.value })}
            title="Stroke color"
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
            disabled={!enabled}
            onChange={(e) => onDrawStyleChange({ fillOpacity: parseFloat(e.target.value) })}
          />
        </label>
        <label className="draw-toolbar-label flex">
          Line
          <input
            type="range"
            min={1}
            max={12}
            step={1}
            value={drawStyle.lineWidth}
            disabled={!enabled}
            onChange={(e) => onDrawStyleChange({ lineWidth: parseInt(e.target.value, 10) })}
          />
        </label>
        <select
          className="draw-toolbar-select"
          value={drawStyle.lineDash}
          disabled={!enabled}
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
      <div className="draw-toolbar-row">
        <button
          type="button"
          className="toolbar-mini"
          onClick={onUndo}
          disabled={!enabled || !canUndo}
          title="Undo drawing"
        >
          Undo
        </button>
        <button
          type="button"
          className="toolbar-mini"
          onClick={onRedo}
          disabled={!enabled || !canRedo}
          title="Redo drawing"
        >
          Redo
        </button>
      </div>
      <div className="draw-toolbar-zoning">
        <span className="draw-toolbar-zoning-title">Zoning tag (new shapes)</span>
        <div className="zone-chips">
          <button
            type="button"
            className={`zone-chip ${activeZonePreset === null ? 'active' : ''}`}
            disabled={!enabled}
            onClick={() => enabled && onZonePresetChange(null)}
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
              disabled={!enabled}
              onClick={() => enabled && onZonePresetChange(z)}
            >
              {z.code}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
