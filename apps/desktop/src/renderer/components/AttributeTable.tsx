import { useMemo, useState } from 'react'
import type { Feature, FeatureCollection } from 'geojson'
import { GeoJSONLayer } from '../types'
import './AttributeTable.css'

interface AttributeTableProps {
  layer: GeoJSONLayer
  onChange: (layerId: string, data: FeatureCollection) => void
  onClose: () => void
}

// Properties that drive rendering/labels — editable, but we surface them; the
// internal source tag is hidden from the grid.
const HIDDEN_PROPS = new Set(['source'])

function columnsOf(features: Feature[]): string[] {
  const cols = new Set<string>()
  for (const f of features) {
    for (const k of Object.keys(f.properties || {})) {
      if (!HIDDEN_PROPS.has(k)) cols.add(k)
    }
  }
  return [...cols]
}

export default function AttributeTable({ layer, onChange, onClose }: AttributeTableProps) {
  const features = useMemo(() => layer.data?.features || [], [layer.data])
  const columns = useMemo(() => columnsOf(features), [features])
  const [newCol, setNewCol] = useState('')

  const commit = (nextFeatures: Feature[]) => {
    onChange(layer.id, { type: 'FeatureCollection', features: nextFeatures })
  }

  const setCell = (rowIdx: number, col: string, value: string) => {
    commit(
      features.map((f, i) =>
        i === rowIdx ? { ...f, properties: { ...(f.properties || {}), [col]: value } } : f,
      ),
    )
  }

  const addColumn = () => {
    const name = newCol.trim()
    if (!name || columns.includes(name)) return
    commit(
      features.map((f) => ({ ...f, properties: { ...(f.properties || {}), [name]: '' } })),
    )
    setNewCol('')
  }

  const deleteColumn = (col: string) => {
    commit(
      features.map((f) => {
        const props = { ...(f.properties || {}) }
        delete props[col]
        return { ...f, properties: props }
      }),
    )
  }

  const deleteRow = (rowIdx: number) => {
    commit(features.filter((_, i) => i !== rowIdx))
  }

  if (features.length === 0) {
    return (
      <div className="attr-table">
        <div className="attr-header">
          <span className="attr-title">Attributes — {layer.name}</span>
          <button className="attr-close" onClick={onClose}>×</button>
        </div>
        <p className="attr-empty">This layer has no features.</p>
      </div>
    )
  }

  return (
    <div className="attr-table">
      <div className="attr-header">
        <span className="attr-title">Attributes — {layer.name}</span>
        <button className="attr-close" onClick={onClose} title="Close">×</button>
      </div>

      <div className="attr-addcol">
        <input
          className="attr-input"
          placeholder="New property (e.g. zone_code)"
          value={newCol}
          onChange={(e) => setNewCol(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addColumn()}
        />
        <button className="attr-btn" onClick={addColumn} disabled={!newCol.trim()}>
          Add
        </button>
      </div>

      <div className="attr-scroll">
        <table>
          <thead>
            <tr>
              <th className="attr-rownum">#</th>
              {columns.map((c) => (
                <th key={c}>
                  <span className="attr-colname" title={c}>{c}</span>
                  <button
                    className="attr-coldel"
                    onClick={() => deleteColumn(c)}
                    title={`Delete property "${c}"`}
                  >
                    ×
                  </button>
                </th>
              ))}
              <th className="attr-rowdel-h" />
            </tr>
          </thead>
          <tbody>
            {features.map((f, rowIdx) => (
              <tr key={rowIdx}>
                <td className="attr-rownum">{rowIdx + 1}</td>
                {columns.map((c) => (
                  <td key={c}>
                    <input
                      className="attr-cell"
                      value={String(f.properties?.[c] ?? '')}
                      onChange={(e) => setCell(rowIdx, c, e.target.value)}
                    />
                  </td>
                ))}
                <td>
                  <button
                    className="attr-rowdel"
                    onClick={() => deleteRow(rowIdx)}
                    title="Delete feature"
                  >
                    🗑
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
