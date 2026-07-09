import { useEffect, useMemo, useState } from 'react'
import { GeoJSONLayer } from '../types'
import './LayerPanel.css'

interface LayerPanelProps {
  layers: GeoJSONLayer[]
  onToggle: (id: string) => void
  onRemove: (id: string) => void
  onZoomTo: (id: string) => void
  onStyle?: (id: string) => void
  activeStyleId?: string | null
  onAttributes?: (id: string) => void
  activeAttrId?: string | null
  onRename?: (id: string, name: string) => void
  onGroupWith?: (sourceId: string, targetId: string) => void
  onUngroup?: (id: string) => void
  onToggleGroup?: (groupId: string, visible: boolean) => void
  onRenameGroup?: (groupId: string, name: string) => void
}

type LayerRow =
  | { type: 'layer'; layer: GeoJSONLayer }
  | { type: 'group'; groupId: string; groupName: string; layers: GeoJSONLayer[] }

export default function LayerPanel({
  layers,
  onToggle,
  onRemove,
  onZoomTo,
  onStyle,
  activeStyleId,
  onAttributes,
  activeAttrId,
  onRename,
  onGroupWith,
  onUngroup,
  onToggleGroup,
  onRenameGroup,
}: LayerPanelProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set())
  const [menu, setMenu] = useState<{ layerId: string; x: number; y: number } | null>(null)

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('keydown', close)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', close)
    }
  }, [menu])

  const rows = useMemo<LayerRow[]>(() => {
    const emittedGroups = new Set<string>()
    const byGroup = new Map<string, GeoJSONLayer[]>()
    layers.forEach((layer) => {
      if (!layer.groupId) return
      byGroup.set(layer.groupId, [...(byGroup.get(layer.groupId) || []), layer])
    })

    return layers.flatMap((layer): LayerRow[] => {
      if (!layer.groupId) return [{ type: 'layer', layer }]
      if (emittedGroups.has(layer.groupId)) return []
      emittedGroups.add(layer.groupId)
      return [{
        type: 'group',
        groupId: layer.groupId,
        groupName: layer.groupName || 'Group',
        layers: byGroup.get(layer.groupId) || [layer],
      }]
    })
  }, [layers])

  const menuLayer = menu ? layers.find((layer) => layer.id === menu.layerId) : null
  const groupTargets = menuLayer
    ? layers.filter((layer) => layer.id !== menuLayer.id)
        .filter((layer) => !menuLayer.groupId || layer.groupId !== menuLayer.groupId)
    : []

  if (layers.length === 0) {
    return (
      <div className="layer-panel-empty">
        <p>No layers loaded</p>
        <p className="hint">Click a .geojson file in Files to add a layer</p>
      </div>
    )
  }

  const getSwatchStyle = (l: GeoJSONLayer) => {
    if (l.geeSpec?.vis_params?.palette) {
      const palette = l.geeSpec.vis_params.palette
      if (Array.isArray(palette)) {
        const cssColors = palette.map((c: string) => c.startsWith('#') ? c : `#${c}`)
        return { background: `linear-gradient(135deg, ${cssColors.join(', ')})` }
      }
    }
    if (l.geeSpec || l.wmsSpec) {
      return { background: 'linear-gradient(135deg, #3b82f6, #10b981, #ef4444)' }
    }
    // Vector layers styling fallback
    if (l.styleSpec?.mode === 'categorized' && l.styleSpec.categories) {
      const colors = l.styleSpec.categories.map((c) => c.color).filter(Boolean)
      if (colors.length > 0) {
        const displayColors = colors.slice(0, 4)
        if (displayColors.length === 1) return { background: displayColors[0] }
        return { background: `linear-gradient(135deg, ${displayColors.join(', ')})` }
      }
    }
    if (l.styleSpec?.mode === 'graduated' && l.styleSpec.rampColors) {
      const colors = l.styleSpec.rampColors.filter(Boolean)
      if (colors.length > 0) {
        const displayColors = colors.slice(0, 4)
        if (displayColors.length === 1) return { background: displayColors[0] }
        return { background: `linear-gradient(135deg, ${displayColors.join(', ')})` }
      }
    }
    return { background: l.fillColor || l.lineColor || l.color }
  }


  const renderLayer = (layer: GeoJSONLayer, grouped = false) => (
    <div
      key={layer.id}
      className={`layer-item ${grouped ? 'grouped' : ''} ${!layer.visible ? 'hidden' : ''}`}
      onContextMenu={(e) => {
        e.preventDefault()
        setMenu({ layerId: layer.id, x: e.clientX, y: e.clientY })
      }}
    >
      <button
        className="layer-visibility"
        onClick={() => onToggle(layer.id)}
        title={layer.visible ? 'Hide layer' : 'Show layer'}
      >
        {layer.visible ? '👁' : '⊘'}
      </button>
      <span
        className={`layer-color ${onStyle && !layer.wmsSpec && !layer.geeSpec ? 'clickable' : ''} ${activeStyleId === layer.id ? 'active' : ''}`}
        style={getSwatchStyle(layer)}
        onClick={() => { if (!layer.wmsSpec && !layer.geeSpec) onStyle?.(layer.id) }}
        title={layer.wmsSpec || layer.geeSpec ? 'Raster layer — no symbology' : 'Symbology & labels'}
      />

      {onRename ? (
        <input
          type="text"
          className="layer-name-input"
          value={layer.name}
          onChange={(e) => onRename(layer.id, e.target.value)}
          title="Rename layer"
        />
      ) : (
        <span className="layer-name" title={layer.name}>
          {layer.name}
        </span>
      )}
      {!layer.wmsSpec && !layer.geeSpec && (
        <span className="layer-count">{layer.data?.features?.length ?? 0}</span>
      )}
      {onAttributes && !layer.wmsSpec && !layer.geeSpec && (layer.data?.features?.length || 0) > 0 && (
        <button
          className={`layer-style ${activeAttrId === layer.id ? 'active' : ''}`}
          onClick={() => onAttributes(layer.id)}
          title="Edit attributes"
        >
          ✎
        </button>
      )}
      {!layer.wmsSpec && !layer.geeSpec && (layer.data?.features?.length || 0) > 0 && (
        <button
          className="layer-zoom"
          onClick={() => onZoomTo(layer.id)}
          title="Zoom to layer"
        >
          ⌖
        </button>
      )}

      <button
        className="layer-remove"
        onClick={() => onRemove(layer.id)}
        title="Remove layer"
      >
        ×
      </button>
    </div>
  )

  return (
    <div className="layer-panel">
      {rows.map((row) => {
        if (row.type === 'layer') return renderLayer(row.layer)

        const collapsed = collapsedGroups.has(row.groupId)
        const allVisible = row.layers.every((layer) => layer.visible)
        return (
          <div key={row.groupId} className="layer-group">
            <div className={`layer-group-header ${!allVisible ? 'hidden' : ''}`}>
              <button
                className="layer-group-toggle"
                onClick={() => {
                  setCollapsedGroups((prev) => {
                    const next = new Set(prev)
                    if (next.has(row.groupId)) next.delete(row.groupId)
                    else next.add(row.groupId)
                    return next
                  })
                }}
                title={collapsed ? 'Expand group' : 'Collapse group'}
              >
                {collapsed ? '▸' : '▾'}
              </button>
              <button
                className="layer-visibility"
                onClick={() => onToggleGroup?.(row.groupId, !allVisible)}
                title={allVisible ? 'Hide group' : 'Show group'}
              >
                {allVisible ? '👁' : '⊘'}
              </button>
              {onRenameGroup ? (
                <input
                  type="text"
                  className="layer-group-name-input"
                  value={row.groupName}
                  onChange={(e) => onRenameGroup(row.groupId, e.target.value)}
                  title="Rename group"
                />
              ) : (
                <span className="layer-group-name" title={row.groupName}>
                  {row.groupName}
                </span>
              )}
              <span className="layer-count">{row.layers.length}</span>
            </div>
            {!collapsed && row.layers.map((layer) => renderLayer(layer, true))}
          </div>
        )
      })}
      {menu && menuLayer && (
        <div
          className="layer-context-menu"
          style={{ left: menu.x, top: menu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="layer-context-title">Group with</div>
          {groupTargets.length === 0 ? (
            <div className="layer-context-empty">No other layers</div>
          ) : (
            groupTargets.map((target) => (
              <button
                key={target.id}
                type="button"
                onClick={() => {
                  onGroupWith?.(menuLayer.id, target.id)
                  setMenu(null)
                }}
              >
                {target.groupName ? `${target.groupName} / ` : ''}{target.name}
              </button>
            ))
          )}
          {menuLayer.groupId && (
            <>
              <div className="layer-context-divider" />
              <button
                type="button"
                onClick={() => {
                  onUngroup?.(menuLayer.id)
                  setMenu(null)
                }}
              >
                Ungroup layer
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
