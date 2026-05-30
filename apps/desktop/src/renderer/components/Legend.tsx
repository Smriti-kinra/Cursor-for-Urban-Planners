import { GeoJSONLayer } from '../types'
import './Legend.css'

interface LegendProps {
  layers: GeoJSONLayer[]
}

function rangeLabel(breaks: number[], i: number): string {
  if (breaks.length === 0) return 'all'
  if (i === 0) return `< ${breaks[0]}`
  if (i === breaks.length) return `≥ ${breaks[breaks.length - 1]}`
  return `${breaks[i - 1]} – ${breaks[i]}`
}

// A live legend derived purely from each visible layer's styleSpec. Renders
// nothing unless at least one visible layer has categorized/graduated styling.
export default function Legend({ layers }: LegendProps) {
  const styled = layers.filter(
    (l) =>
      l.visible &&
      l.styleSpec &&
      (l.styleSpec.mode === 'categorized' || l.styleSpec.mode === 'graduated'),
  )
  if (styled.length === 0) return null

  return (
    <div className="map-legend">
      {styled.map((l) => {
        const s = l.styleSpec!
        return (
          <div key={l.id} className="legend-block">
            <div className="legend-title">
              {l.name}
              {s.property ? <span className="legend-prop"> · {s.property}</span> : null}
            </div>
            {s.mode === 'categorized' &&
              (s.categories || []).map((c) => (
                <div key={c.value} className="legend-row">
                  <span className="legend-swatch" style={{ background: c.color }} />
                  <span className="legend-text">{c.value || '(empty)'}</span>
                </div>
              ))}
            {s.mode === 'graduated' &&
              (s.rampColors || []).map((color, i) => (
                <div key={i} className="legend-row">
                  <span className="legend-swatch" style={{ background: color }} />
                  <span className="legend-text">{rangeLabel(s.breaks || [], i)}</span>
                </div>
              ))}
          </div>
        )
      })}
    </div>
  )
}
