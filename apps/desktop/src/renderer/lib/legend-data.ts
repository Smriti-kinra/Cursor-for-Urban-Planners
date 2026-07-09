// Single source of truth for legend content. Both the on-screen Legend overlay
// and the exported figure's baked-in legend derive their rows from here, so the
// two never drift apart.

import type { GeoJSONLayer } from '../types'

export interface LegendRow {
  color: string
  label: string
}

export interface LegendEntry {
  /** Layer name. */
  title: string
  /** Property the styling is driven by, if any. */
  property?: string
  rows: LegendRow[]
}

function rangeLabel(breaks: number[], i: number): string {
  if (breaks.length === 0) return 'all'
  if (i === 0) return `< ${breaks[0]}`
  if (i === breaks.length) return `≥ ${breaks[breaks.length - 1]}`
  return `${breaks[i - 1]} – ${breaks[i]}`
}

/** Build legend entries from the visible, categorized/graduated layers. */
export function buildLegendEntries(layers: GeoJSONLayer[]): LegendEntry[] {
  const entries: LegendEntry[] = []
  for (const l of layers) {
    if (!l.visible) continue
    const s = l.styleSpec
    if (s) {
      if (s.mode === 'categorized' && s.categories?.length) {
        entries.push({
          title: l.name,
          property: s.property,
          rows: s.categories.map((c) => ({ color: c.color, label: c.value || '(empty)' })),
        })
      } else if (s.mode === 'graduated' && s.rampColors?.length) {
        entries.push({
          title: l.name,
          property: s.property,
          rows: s.rampColors.map((color, i) => ({
            color,
            label: rangeLabel(s.breaks || [], i),
          })),
        })
      }
    } else if (l.geeSpec?.vis_params) {
      const vis = l.geeSpec.vis_params
      const palette = vis.palette
      if (Array.isArray(palette)) {
        const min = vis.min ?? 0
        const max = vis.max ?? 100
        const labels = vis.palette_labels || []
        
        const rows = palette.map((color: string, i: number) => {
          const hexColor = color.startsWith('#') ? color : `#${color}`
          let label = ''
          if (labels[i]) {
            label = labels[i]
          } else {
            const val = min + (i / (palette.length - 1)) * (max - min)
            label = val % 1 === 0 ? val.toString() : val.toFixed(1)
          }
          return { color: hexColor, label }
        })
        
        entries.push({
          title: l.name,
          property: 'Value',
          rows,
        })
      }
    }
  }

  return entries
}
