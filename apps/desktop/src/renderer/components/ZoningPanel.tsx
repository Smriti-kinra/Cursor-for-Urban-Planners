import { DEFAULT_ZONE_PRESETS } from '../types'
import './ZoningPanel.css'

export default function ZoningPanel() {
  return (
    <div className="zoning-panel">
      <h4 className="zoning-title">Zoning legend</h4>
      <p className="zoning-intro">
        Load a GeoJSON file containing a <code>zone_code</code> property on each feature to use zoning analysis.
        Ask the assistant to <code>analyze_zones</code> or <code>detect_zone_overlaps</code> on any loaded layer.
      </p>
      <ul className="zoning-legend">
        {DEFAULT_ZONE_PRESETS.map((z) => (
          <li key={z.code}>
            <span className="zoning-swatch" style={{ background: z.color }} />
            <strong>{z.code}</strong>
            <span className="zoning-desc">{z.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
