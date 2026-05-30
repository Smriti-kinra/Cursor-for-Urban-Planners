import { useMemo } from 'react'
import type { Feature } from 'geojson'
import { GeoJSONLayer, LayerStyleSpec, ClassificationMethod } from '../types'
import {
  COLOR_RAMPS,
  DEFAULT_RAMP,
  buildCategories,
  computeBreaks,
  rampColorsForClasses,
} from '../lib/classify'
import './SymbologyPanel.css'

interface SymbologyPanelProps {
  layer: GeoJSONLayer
  onChange: (layerId: string, styleSpec: LayerStyleSpec) => void
  onClose: () => void
}

const SEQUENTIAL_RAMPS = ['YlOrRd', 'Blues', 'Greens', 'Purples', 'Reds']

// Collect the union of property keys, and which of them are numeric, across a
// feature sample. Sampling keeps this cheap on large layers.
function inspectProperties(features: Feature[]): { all: string[]; numeric: Set<string> } {
  const all = new Set<string>()
  const numericVotes = new Map<string, { num: number; total: number }>()
  const sample = features.slice(0, 500)
  for (const f of sample) {
    const props = f.properties || {}
    for (const [k, v] of Object.entries(props)) {
      all.add(k)
      const rec = numericVotes.get(k) || { num: 0, total: 0 }
      rec.total += 1
      if (typeof v === 'number' || (v !== '' && v != null && Number.isFinite(Number(v)))) rec.num += 1
      numericVotes.set(k, rec)
    }
  }
  const numeric = new Set<string>()
  for (const [k, rec] of numericVotes) {
    if (rec.total > 0 && rec.num / rec.total >= 0.8) numeric.add(k)
  }
  return { all: [...all], numeric }
}

export default function SymbologyPanel({ layer, onChange, onClose }: SymbologyPanelProps) {
  const features = layer.data?.features || []
  const { all: allProps, numeric: numericProps } = useMemo(
    () => inspectProperties(features),
    [features],
  )

  const spec: LayerStyleSpec = layer.styleSpec ?? { mode: 'simple' }
  const emit = (next: LayerStyleSpec) => onChange(layer.id, next)

  // ── Mode ──
  const setMode = (mode: LayerStyleSpec['mode']) => {
    if (mode === 'simple') {
      emit({ mode: 'simple', opacity: spec.opacity, label: spec.label })
      return
    }
    if (mode === 'categorized') {
      const prop = spec.property && allProps.includes(spec.property) ? spec.property : allProps[0]
      recomputeCategorized(prop, spec.rampName || 'category')
      return
    }
    // graduated
    const numProp = spec.property && numericProps.has(spec.property)
      ? spec.property
      : [...numericProps][0]
    recomputeGraduated(numProp, spec.rampName || DEFAULT_RAMP, spec.breaks ? spec.breaks.length + 1 : 5, spec.classification || 'quantile')
  }

  // ── Categorized ──
  const recomputeCategorized = (property: string | undefined, rampName: string) => {
    if (!property) { emit({ ...spec, mode: 'categorized' }); return }
    const values = features.map((f) => String(f.properties?.[property] ?? ''))
    emit({
      ...spec,
      mode: 'categorized',
      property,
      categories: buildCategories(values, property, rampName),
      otherColor: layer.color,
      rampName,
      breaks: undefined,
      rampColors: undefined,
    })
  }

  const setCategoryColor = (value: string, color: string) => {
    if (!spec.categories) return
    emit({
      ...spec,
      categories: spec.categories.map((c) => (c.value === value ? { ...c, color } : c)),
    })
  }

  // ── Graduated ──
  const recomputeGraduated = (
    property: string | undefined,
    rampName: string,
    classes: number,
    method: ClassificationMethod,
  ) => {
    if (!property) { emit({ ...spec, mode: 'graduated' }); return }
    const nums = features
      .map((f) => Number(f.properties?.[property]))
      .filter((n) => Number.isFinite(n))
    const breaks = computeBreaks(nums, classes, method)
    emit({
      ...spec,
      mode: 'graduated',
      property,
      breaks,
      rampColors: rampColorsForClasses(rampName, breaks.length + 1),
      classification: method,
      rampName,
      categories: undefined,
    })
  }

  // ── Labels ──
  const setLabel = (patch: Partial<NonNullable<LayerStyleSpec['label']>>) => {
    const cur = spec.label ?? { enabled: false, property: allProps[0] || '' }
    emit({ ...spec, label: { ...cur, ...patch } })
  }

  return (
    <div className="symbology-panel">
      <div className="sym-header">
        <span className="sym-title">Symbology — {layer.name}</span>
        <button className="sym-close" onClick={onClose} title="Close">×</button>
      </div>

      {/* Mode */}
      <div className="sym-row">
        <label className="sym-label">Color by</label>
        <div className="sym-modes">
          {(['simple', 'categorized', 'graduated'] as const).map((m) => (
            <button
              key={m}
              className={`sym-mode ${spec.mode === m ? 'active' : ''}`}
              onClick={() => setMode(m)}
            >
              {m === 'simple' ? 'Single' : m === 'categorized' ? 'Category' : 'Graduated'}
            </button>
          ))}
        </div>
      </div>

      {/* Categorized controls */}
      {spec.mode === 'categorized' && (
        <>
          <div className="sym-row">
            <label className="sym-label">Property</label>
            <select
              className="sym-select"
              value={spec.property || ''}
              onChange={(e) => recomputeCategorized(e.target.value, spec.rampName || 'category')}
            >
              {allProps.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="sym-categories">
            {(spec.categories || []).map((c) => (
              <div key={c.value} className="sym-cat">
                <input
                  type="color"
                  value={c.color}
                  onChange={(e) => setCategoryColor(c.value, e.target.value)}
                />
                <span className="sym-cat-value" title={c.value}>{c.value || '(empty)'}</span>
              </div>
            ))}
            {(spec.categories?.length ?? 0) === 0 && (
              <p className="sym-hint">No values found for this property.</p>
            )}
          </div>
        </>
      )}

      {/* Graduated controls */}
      {spec.mode === 'graduated' && (
        <>
          <div className="sym-row">
            <label className="sym-label">Property</label>
            <select
              className="sym-select"
              value={spec.property || ''}
              onChange={(e) =>
                recomputeGraduated(
                  e.target.value, spec.rampName || DEFAULT_RAMP,
                  spec.breaks ? spec.breaks.length + 1 : 5,
                  spec.classification || 'quantile',
                )
              }
            >
              {[...numericProps].map((p) => <option key={p} value={p}>{p}</option>)}
              {numericProps.size === 0 && <option value="">(no numeric properties)</option>}
            </select>
          </div>
          <div className="sym-row">
            <label className="sym-label">Method</label>
            <select
              className="sym-select"
              value={spec.classification || 'quantile'}
              onChange={(e) =>
                recomputeGraduated(
                  spec.property, spec.rampName || DEFAULT_RAMP,
                  spec.breaks ? spec.breaks.length + 1 : 5,
                  e.target.value as ClassificationMethod,
                )
              }
            >
              <option value="quantile">Quantile</option>
              <option value="equal-interval">Equal interval</option>
            </select>
          </div>
          <div className="sym-row">
            <label className="sym-label">Classes</label>
            <select
              className="sym-select"
              value={spec.breaks ? spec.breaks.length + 1 : 5}
              onChange={(e) =>
                recomputeGraduated(
                  spec.property, spec.rampName || DEFAULT_RAMP,
                  Number(e.target.value), spec.classification || 'quantile',
                )
              }
            >
              {[3, 4, 5, 6, 7].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="sym-row">
            <label className="sym-label">Ramp</label>
            <div className="sym-ramps">
              {SEQUENTIAL_RAMPS.map((r) => (
                <button
                  key={r}
                  className={`sym-ramp ${spec.rampName === r ? 'active' : ''}`}
                  title={r}
                  onClick={() =>
                    recomputeGraduated(
                      spec.property, r,
                      spec.breaks ? spec.breaks.length + 1 : 5,
                      spec.classification || 'quantile',
                    )
                  }
                >
                  {COLOR_RAMPS[r].map((c, i) => (
                    <span key={i} style={{ background: c }} />
                  ))}
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Labels */}
      <div className="sym-row sym-row-divider">
        <label className="sym-label">
          <input
            type="checkbox"
            checked={!!spec.label?.enabled}
            onChange={(e) => setLabel({ enabled: e.target.checked, property: spec.label?.property || allProps[0] || '' })}
          />
          {' '}Labels
        </label>
      </div>
      {spec.label?.enabled && (
        <div className="sym-row">
          <label className="sym-label">Text</label>
          <select
            className="sym-select"
            value={spec.label.property || ''}
            onChange={(e) => setLabel({ property: e.target.value })}
          >
            {allProps.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
      )}
    </div>
  )
}
