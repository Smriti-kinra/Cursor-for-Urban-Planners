import { DEFAULT_ZONE_PRESETS } from '../types'
import './ZoningPanel.css'

/** Legend for standard zoning colors (draw tagging uses DrawToolbar chips). */
export default function ZoningPanel() {
  return (
    <div className="zoning-panel">
      <h4 className="zoning-title">Zoning legend</h4>
      <p className="zoning-intro">
        Pick a zone chip in the draw toolbar, then draw a polygon — features get <code>zone_code</code>{' '}
        for analysis with the assistant (<code>analyze_zones</code>, <code>detect_zone_overlaps</code>).
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
