import { GeoJSONLayer } from '../types'
import { buildLegendEntries } from '../lib/legend-data'
import './Legend.css'

interface LegendProps {
  layers: GeoJSONLayer[]
}

// A live legend derived purely from each visible layer's styleSpec (via the
// shared buildLegendEntries helper, which the exported figure also uses).
// Renders nothing unless at least one visible layer has categorized/graduated
// styling.
export default function Legend({ layers }: LegendProps) {
  const entries = buildLegendEntries(layers)
  if (entries.length === 0) return null

  return (
    <div className="map-legend">
      {entries.map((entry, i) => (
        <div key={i} className="legend-block">
          <div className="legend-title">
            {entry.title}
            {entry.property ? <span className="legend-prop"> · {entry.property}</span> : null}
          </div>
          {entry.rows.map((row, j) => (
            <div key={j} className="legend-row">
              <span className="legend-swatch" style={{ background: row.color }} />
              <span className="legend-text">{row.label}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
