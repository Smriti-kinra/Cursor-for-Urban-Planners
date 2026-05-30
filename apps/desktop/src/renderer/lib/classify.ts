// Classification + color-ramp helpers for data-driven symbology.
//
// Breaks are computed on the frontend because the full feature data already
// lives in React state (the backend's mapContext view is lossy). Used by the
// `style_layer` action handler in App.tsx and by SymbologyPanel.

import type { ClassificationMethod } from '../types'
import { DEFAULT_ZONE_PRESETS } from '../types'

// Sequential + qualitative ColorBrewer-style ramps. Sequential ramps are
// indexed by class count at call sites (slice to N); the 'category' ramp is a
// qualitative palette cycled by index.
export const COLOR_RAMPS: Record<string, string[]> = {
  YlOrRd: ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026'],
  Blues: ['#eff3ff', '#bdd7e7', '#6baed6', '#3182bd', '#08519c'],
  Greens: ['#edf8e9', '#bae4b3', '#74c476', '#31a354', '#006d2c'],
  Purples: ['#f2f0f7', '#cbc9e2', '#9e9ac8', '#756bb1', '#54278f'],
  Reds: ['#fee5d9', '#fcae91', '#fb6a4a', '#de2d26', '#a50f15'],
  // Qualitative palette for categorized styling (matches LAYER_COLORS spirit).
  category: [
    '#4363d8', '#3cb44b', '#e6194b', '#f58231', '#911eb4',
    '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
    '#9a6324', '#808000',
  ],
}

export const DEFAULT_RAMP = 'YlOrRd'

/** Zone code → preset color, for seeding categorized styling on zone_code. */
const ZONE_PRESET_COLORS: Record<string, string> = Object.fromEntries(
  DEFAULT_ZONE_PRESETS.map((p) => [p.code.toLowerCase(), p.color]),
)

/**
 * Compute ascending class boundaries for a numeric column.
 * Returns `classes - 1` interior breaks (so there are `classes` buckets).
 *   equal-interval: even splits between min and max.
 *   quantile:       equal-count splits over the sorted values.
 */
export function computeBreaks(
  values: number[],
  classes: number,
  method: ClassificationMethod,
): number[] {
  const nums = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b)
  const k = Math.max(2, Math.min(classes, 9))
  if (nums.length === 0) return []
  const min = nums[0]
  const max = nums[nums.length - 1]
  if (min === max) return [] // single value → one bucket

  const breaks: number[] = []
  if (method === 'equal-interval') {
    const step = (max - min) / k
    for (let i = 1; i < k; i++) breaks.push(round(min + step * i))
  } else {
    // quantile
    for (let i = 1; i < k; i++) {
      const idx = Math.round((i * nums.length) / k)
      breaks.push(round(nums[Math.min(idx, nums.length - 1)]))
    }
  }
  // De-duplicate (quantile on skewed data can repeat a boundary).
  return [...new Set(breaks)]
}

/** Distinct string values of a column, most-frequent first, capped at `max`. */
export function distinctCategories(values: string[], max = 12): string[] {
  const counts = new Map<string, number>()
  for (const raw of values) {
    const v = String(raw ?? '').trim()
    if (!v) continue
    counts.set(v, (counts.get(v) || 0) + 1)
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, max)
    .map(([v]) => v)
}

/**
 * Build an ordered {value,color} list for categorized styling. Zone-code-like
 * properties reuse the planning zone presets; everything else cycles the
 * qualitative ramp.
 */
export function buildCategories(
  values: string[],
  property: string,
  rampName = 'category',
): Array<{ value: string; color: string }> {
  const ramp = COLOR_RAMPS[rampName] || COLOR_RAMPS.category
  const isZone = property.toLowerCase().includes('zone')
  return distinctCategories(values).map((value, i) => {
    const preset = isZone ? ZONE_PRESET_COLORS[value.toLowerCase()] : undefined
    return { value, color: preset || ramp[i % ramp.length] }
  })
}

/**
 * Pick `classes` colors from a sequential ramp. If the ramp has fewer stops
 * than needed, the last stop repeats (rare; ramps ship 5 stops, max 9 classes).
 */
export function rampColorsForClasses(rampName: string, classes: number): string[] {
  const ramp = COLOR_RAMPS[rampName] || COLOR_RAMPS[DEFAULT_RAMP]
  if (classes <= ramp.length) {
    // Spread across the ramp so endpoints are used (e.g. 3 of 5 → 0,2,4).
    if (classes === ramp.length) return [...ramp]
    const out: string[] = []
    for (let i = 0; i < classes; i++) {
      out.push(ramp[Math.round((i * (ramp.length - 1)) / (classes - 1))])
    }
    return out
  }
  const out = [...ramp]
  while (out.length < classes) out.push(ramp[ramp.length - 1])
  return out
}

function round(n: number): number {
  // Keep break labels readable without destroying precision on small ranges.
  const abs = Math.abs(n)
  if (abs >= 100) return Math.round(n)
  if (abs >= 1) return Math.round(n * 100) / 100
  return Math.round(n * 10000) / 10000
}
