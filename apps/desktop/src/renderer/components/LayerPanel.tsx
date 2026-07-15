import { useEffect, useMemo, useState, useRef } from 'react'
import { GeoJSONLayer, LayerStyleSpec } from '../types'
import SymbologyPanel from './SymbologyPanel'
import AttributeTable from './AttributeTable'
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
  onGroupMulti?: (ids: string[]) => void
  onUngroup?: (id: string) => void
  onToggleGroup?: (groupId: string, visible: boolean) => void
  onRenameGroup?: (groupId: string, name: string) => void
  // Props to drive the popups inside LayerPanel
  onStyleChange?: (layerId: string, styleSpec: LayerStyleSpec) => void
  onUpdateLayer?: (layerId: string, updates: Partial<GeoJSONLayer>) => void
  onAttributesChange?: (layerId: string, data: any) => void
  onReorderLayers?: (layers: GeoJSONLayer[]) => void
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
  onGroupMulti,
  onUngroup,
  onToggleGroup,
  onRenameGroup,
  onStyleChange,
  onUpdateLayer,
  onAttributesChange,
  onReorderLayers,
}: LayerPanelProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set())
  // menu carries the right-clicked layerId + cursor pos + snapshot of selected IDs at time of right-click
  const [menu, setMenu] = useState<{ layerId: string; x: number; y: number; selectedIds: Set<string> } | null>(null)

  // multi-select state
  const [selectedLayerIds, setSelectedLayerIds] = useState<Set<string>>(new Set())
  const panelRef = useRef<HTMLDivElement>(null)

  // Clear selection when clicking anywhere outside the panel
  useEffect(() => {
    const handleOutsideMouseDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setSelectedLayerIds(new Set())
      }
    }
    document.addEventListener('mousedown', handleOutsideMouseDown)
    return () => document.removeEventListener('mousedown', handleOutsideMouseDown)
  }, [])

  // drag-and-drop state
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [draggedType, setDraggedType] = useState<'layer' | 'group' | null>(null)
  const [dragOverId, setDragOverId] = useState<string | null>(null)
  const [dropPosition, setDropPosition] = useState<'before' | 'after' | null>(null)

  const menuLayer = useMemo(
    () => (menu ? layers.find((l) => l.id === menu.layerId) : null),
    [menu, layers],
  )

  const groupTargets = useMemo(() => {
    if (!menuLayer) return []
    // Allow grouping with other ungrouped layers, or existing group leaders.
    const uniqueGroups = new Map<string, string>() // groupId -> name
    layers.forEach((l) => {
      if (l.groupId && l.groupId !== menuLayer.groupId) {
        uniqueGroups.set(l.groupId, l.groupName || l.groupId)
      }
    })

    const groupLeaders = Array.from(uniqueGroups.entries()).map(([id, name]) => ({
      id,
      name: '',
      groupName: name,
    }))

    const rawLayers = layers
      .filter((l) => l.id !== menuLayer.id && !l.groupId)
      .map((l) => ({ id: l.id, name: l.name, groupName: '' }))

    return [...groupLeaders, ...rawLayers]
  }, [menuLayer, layers])

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

  if (layers.length === 0) {
    return (
      <div className="layer-panel-empty">
        <p>No layers loaded</p>
        <p className="hint">Click a .geojson file in Files to add a layer</p>
      </div>
    )
  }

  const getSwatchStyle = (l: GeoJSONLayer): React.CSSProperties => {
    if (l.styleSpec?.mode === 'categorized' && l.styleSpec.categories) {
      const colors = l.styleSpec.categories.map((c) => c.color).filter(Boolean)
      if (colors.length > 0) {
        const displayColors = colors.slice(0, 4)
        if (displayColors.length === 1) return { background: displayColors[0] }
        return { background: `linear-gradient(135deg, ${displayColors.join(', ')})` }
      }
    }
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

  // Selection handler — Cmd/Ctrl or Shift for multi-select, plain click = single select (toggle if already sole)
  const handleSelect = (layerId: string, e: React.MouseEvent) => {
    setSelectedLayerIds((prev) => {
      const next = new Set(prev)
      if (e.ctrlKey || e.metaKey) {
        if (next.has(layerId)) next.delete(layerId)
        else next.add(layerId)
      } else if (e.shiftKey && prev.size > 0) {
        const lastSelected = Array.from(prev).pop()!
        const idx1 = layers.findIndex((l) => l.id === lastSelected)
        const idx2 = layers.findIndex((l) => l.id === layerId)
        if (idx1 !== -1 && idx2 !== -1) {
          const start = Math.min(idx1, idx2)
          const end = Math.max(idx1, idx2)
          for (let i = start; i <= end; i++) {
            next.add(layers[i].id)
          }
        }
      } else {
        // Plain click: if this layer is already the sole selection, deselect; otherwise select only it
        if (next.size === 1 && next.has(layerId)) {
          next.clear()
        } else {
          next.clear()
          next.add(layerId)
        }
      }
      return next
    })
  }

  // Right-click: add the right-clicked layer to selection (without clearing others), then show context menu
  const handleContextMenu = (layerId: string, e: React.MouseEvent) => {
    e.preventDefault()
    setSelectedLayerIds((prev) => {
      const next = new Set(prev)
      // Always include the right-clicked layer
      next.add(layerId)
      // Snapshot used by context menu rendering
      setMenu({ layerId, x: e.clientX, y: e.clientY, selectedIds: next })
      return next
    })
  }

  // Drag and Drop handlers
  const handleDragStart = (id: string, e: React.DragEvent) => {
    setDraggedId(id)
    setDraggedType('layer')
    e.dataTransfer.setData('text/plain', id)
  }

  const handleDragOver = (id: string, e: React.DragEvent) => {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const relativeY = e.clientY - rect.top
    const pos = relativeY < rect.height / 2 ? 'before' : 'after'
    setDragOverId(id)
    setDropPosition(pos)
  }

  const handleDragEnd = () => {
    setDraggedId(null)
    setDraggedType(null)
    setDragOverId(null)
    setDropPosition(null)
  }

  const handleDrop = (targetId: string, e: React.DragEvent) => {
    e.preventDefault()
    if (!draggedId) return

    let draggedLayerIds: string[] = []
    if (draggedType === 'group') {
      draggedLayerIds = layers.filter((l) => l.groupId === draggedId).map((l) => l.id)
    } else {
      if (selectedLayerIds.has(draggedId)) {
        draggedLayerIds = layers.filter((l) => selectedLayerIds.has(l.id)).map((l) => l.id)
      } else {
        draggedLayerIds = [draggedId]
      }
    }

    if (draggedLayerIds.length === 0) return

    const targetLayer = layers.find((l) => l.id === targetId)
    const targetGroupId = targetLayer?.groupId || null
    const targetGroupName = targetLayer?.groupName || null

    const remainingLayers = layers.filter((l) => !draggedLayerIds.includes(l.id))
    let insertIndex = remainingLayers.findIndex((l) => l.id === targetId)

    if (insertIndex === -1) {
      // Drop target might be a group header ID
      const groupLayers = remainingLayers.filter((l) => l.groupId === targetId)
      if (groupLayers.length > 0) {
        insertIndex = dropPosition === 'before'
          ? remainingLayers.indexOf(groupLayers[0])
          : remainingLayers.indexOf(groupLayers[groupLayers.length - 1]) + 1
      } else {
        insertIndex = remainingLayers.length
      }
    } else {
      if (dropPosition === 'after') {
        insertIndex += 1
      }
    }

    const updatedDraggedLayers = layers
      .filter((l) => draggedLayerIds.includes(l.id))
      .map((l) => ({
        ...l,
        groupId: targetGroupId,
        groupName: targetGroupName,
      }))

    const newLayers = [
      ...remainingLayers.slice(0, insertIndex),
      ...updatedDraggedLayers,
      ...remainingLayers.slice(insertIndex),
    ]

    onReorderLayers?.(newLayers)
    handleDragEnd()
  }

  const renderLayer = (layer: GeoJSONLayer, index: number, total: number, grouped = false) => {
    return (
      <LayerItemRow
        key={layer.id}
        layer={layer}
        grouped={grouped}
        activeStyleId={activeStyleId}
        activeAttrId={activeAttrId}
        onToggle={onToggle}
        onRemove={onRemove}
        onZoomTo={onZoomTo}
        onStyle={onStyle}
        onAttributes={onAttributes}
        onRename={onRename}
        onStyleChange={onStyleChange}
        onUpdateLayer={onUpdateLayer}
        onAttributesChange={onAttributesChange}
        onContextMenu={(e) => handleContextMenu(layer.id, e)}
        getSwatchStyle={getSwatchStyle}
        isSelected={selectedLayerIds.has(layer.id)}
        dragOverId={dragOverId}
        dropPosition={dropPosition}
        onSelect={handleSelect}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onDragEnd={handleDragEnd}
      />
    )
  }

  return (
    <div
      ref={panelRef}
      className="layer-panel"
      onClick={(e) => {
        // Clicking the panel background (not a row) clears selection
        if (e.target === e.currentTarget) setSelectedLayerIds(new Set())
      }}
    >
      {rows.map((row, idx) => {
        if (row.type === 'layer') return renderLayer(row.layer, idx, rows.length)

        const collapsed = collapsedGroups.has(row.groupId)
        const allVisible = row.layers.every((layer) => layer.visible)
        return (
          <div key={row.groupId} className="layer-group">
            <div
              className={`layer-group-header ${!allVisible ? 'hidden' : ''} ${dragOverId === row.groupId ? `drag-over-${dropPosition}` : ''}`}
              draggable={true}
              onDragStart={(e) => {
                setDraggedId(row.groupId)
                setDraggedType('group')
                e.dataTransfer.setData('text/plain', row.groupId)
              }}
              onDragOver={(e) => {
                e.preventDefault()
                const rect = e.currentTarget.getBoundingClientRect()
                const relativeY = e.clientY - rect.top
                const pos = relativeY < rect.height / 2 ? 'before' : 'after'
                setDragOverId(row.groupId)
                setDropPosition(pos)
              }}
              onDragEnd={handleDragEnd}
              onDrop={(e) => handleDrop(row.groupId, e)}
            >
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
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
              >
                {collapsed ? (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="9 18 15 12 9 6"></polyline>
                  </svg>
                ) : (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="6 9 12 15 18 9"></polyline>
                  </svg>
                )}
              </button>
              <button
                className="layer-visibility"
                onClick={() => onToggleGroup?.(row.groupId, !allVisible)}
                title={allVisible ? 'Hide group' : 'Show group'}
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
              >
                {allVisible ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                    <line x1="1" y1="1" x2="23" y2="23"></line>
                  </svg>
                )}
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
            {!collapsed && row.layers.map((layer, subIdx) => renderLayer(layer, idx + subIdx + 1, rows.length, true))}
          </div>
        )
      })}
      {menu && menuLayer && (() => {
        const menuSelectedIds = menu.selectedIds ?? new Set([menu.layerId])
        const isMulti = menuSelectedIds.size > 1
        // All selected layers that are in a group
        const selectedInGroup = Array.from(menuSelectedIds).filter(
          (id) => layers.find((l) => l.id === id)?.groupId
        )

        return (
          <div
            className="layer-context-menu"
            style={{ left: menu.x, top: menu.y }}
            onClick={(e) => e.stopPropagation()}
          >
            {isMulti ? (
              // ── Multi-select menu ──
              <>
                <div className="layer-context-title">
                  {menuSelectedIds.size} layers selected
                </div>
                <button
                  type="button"
                  onClick={() => {
                    onGroupMulti?.(Array.from(menuSelectedIds))
                    setMenu(null)
                    setSelectedLayerIds(new Set())
                  }}
                >
                  Group these layers
                </button>
                {selectedInGroup.length > 0 && (
                  <>
                    <div className="layer-context-divider" />
                    <button
                      type="button"
                      onClick={() => {
                        selectedInGroup.forEach((id) => onUngroup?.(id))
                        setMenu(null)
                        setSelectedLayerIds(new Set())
                      }}
                    >
                      {selectedInGroup.length === menuSelectedIds.size
                        ? 'Ungroup all selected'
                        : `Ungroup ${selectedInGroup.length} grouped layer${selectedInGroup.length > 1 ? 's' : ''}`}
                    </button>
                  </>
                )}
              </>
            ) : (
              // ── Single-layer menu ──
              <>
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
              </>
            )}
          </div>
        )
      })()}
    </div>
  )
}

interface LayerItemRowProps {
  layer: GeoJSONLayer
  grouped: boolean
  activeStyleId: string | null
  activeAttrId: string | null
  onToggle: (id: string) => void
  onRemove: (id: string) => void
  onZoomTo: (id: string) => void
  onStyle?: (id: string) => void
  onAttributes?: (id: string) => void
  onRename?: (id: string, name: string) => void
  onStyleChange?: (layerId: string, styleSpec: LayerStyleSpec) => void
  onUpdateLayer?: (layerId: string, updates: Partial<GeoJSONLayer>) => void
  onAttributesChange?: (layerId: string, data: any) => void
  onContextMenu: (e: React.MouseEvent) => void
  getSwatchStyle: (l: GeoJSONLayer) => React.CSSProperties

  // selection & drag-and-drop
  isSelected: boolean
  dragOverId: string | null
  dropPosition: 'before' | 'after' | null
  onSelect: (id: string, e: React.MouseEvent) => void
  onDragStart: (id: string, e: React.DragEvent) => void
  onDragOver: (id: string, e: React.DragEvent) => void
  onDrop: (id: string, e: React.DragEvent) => void
  onDragEnd: () => void
}

function LayerItemRow({
  layer,
  grouped,
  activeStyleId,
  activeAttrId,
  onToggle,
  onRemove,
  onZoomTo,
  onStyle,
  onAttributes,
  onRename,
  onStyleChange,
  onUpdateLayer,
  onAttributesChange,
  onContextMenu,
  getSwatchStyle,
  isSelected,
  dragOverId,
  dropPosition,
  onSelect,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: LayerItemRowProps) {
  const isStyleActive = activeStyleId === layer.id
  const isAttrActive = activeAttrId === layer.id
  const [showAbove, setShowAbove] = useState(false)
  const rowRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isStyleActive || isAttrActive) {
      const el = rowRef.current
      if (el) {
        const container = el.closest('.layer-panel')
        if (container) {
          const rect = el.getBoundingClientRect()
          const containerRect = container.getBoundingClientRect()
          const spaceBelow = containerRect.bottom - rect.bottom
          // If less than 300px space remains below this row inside the scrollable container, pop UP
          setShowAbove(spaceBelow < 300)
        }
      }
    }
  }, [isStyleActive, isAttrActive])

  useEffect(() => {
    if (!isStyleActive && !isAttrActive) return
    const handleOutsideClick = (e: MouseEvent) => {
      if (rowRef.current && !rowRef.current.contains(e.target as Node)) {
        if (isStyleActive) onStyle?.(layer.id)
        if (isAttrActive) onAttributes?.(layer.id)
      }
    }
    window.addEventListener('click', handleOutsideClick, true)
    return () => {
      window.removeEventListener('click', handleOutsideClick, true)
    }
  }, [isStyleActive, isAttrActive, layer.id, onStyle, onAttributes])

  return (
    <div
      ref={rowRef}
      className={`layer-item ${grouped ? 'grouped' : ''} ${!layer.visible ? 'hidden' : ''} ${isSelected ? 'selected' : ''} ${dragOverId === layer.id ? `drag-over-${dropPosition}` : ''}`}
      style={{ position: 'relative', cursor: 'grab' }}
      onContextMenu={onContextMenu}
      draggable={true}
      onDragStart={(e) => onDragStart(layer.id, e)}
      onDragOver={(e) => onDragOver(layer.id, e)}
      onDrop={(e) => onDrop(layer.id, e)}
      onDragEnd={onDragEnd}
      onClick={(e) => {
        const target = e.target as HTMLElement
        if (target.closest('button') || target.closest('.layer-color') || target.closest('input')) {
          return
        }
        onSelect(layer.id, e)
      }}
    >
      <button
        className="layer-visibility"
        onClick={() => onToggle(layer.id)}
        title={layer.visible ? 'Hide layer' : 'Show layer'}
        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
      >
        {layer.visible ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
            <circle cx="12" cy="12" r="3"></circle>
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
            <line x1="1" y1="1" x2="23" y2="23"></line>
          </svg>
        )}
      </button>
      <span
        className={`layer-color ${onStyle && (!layer.wmsSpec && !layer.geeSpec || layer.rasterOverlaySpec) ? 'clickable' : ''} ${activeStyleId === layer.id ? 'active' : ''}`}
        style={getSwatchStyle(layer)}
        onClick={() => { if (!layer.wmsSpec && !layer.geeSpec || layer.rasterOverlaySpec) onStyle?.(layer.id) }}
        title={layer.rasterOverlaySpec ? 'Raster overlay alignment & opacity' : (layer.wmsSpec || layer.geeSpec ? 'Raster layer — no symbology' : 'Symbology & labels')}
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
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 20h9"></path>
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
          </svg>
        </button>
      )}
      {!layer.wmsSpec && !layer.geeSpec && (layer.data?.features?.length || 0) > 0 && (
        <button
          className="layer-zoom"
          onClick={() => onZoomTo(layer.id)}
          title="Zoom to layer"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <circle cx="12" cy="12" r="3" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
          </svg>
        </button>
      )}

      <button
        className="layer-remove"
        onClick={() => onRemove(layer.id)}
        title="Remove layer"
        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>

      {isStyleActive && onStyleChange && (
        <div className={`layer-popup-container ${showAbove ? 'popup-above' : 'popup-below'}`}>
          <SymbologyPanel
            layer={layer}
            onChange={onStyleChange}
            onClose={() => onStyle?.(layer.id)}
            onUpdateLayer={onUpdateLayer}
          />
        </div>
      )}

      {isAttrActive && onAttributesChange && (
        <div className={`layer-popup-container ${showAbove ? 'popup-above' : 'popup-below'}`}>
          <AttributeTable
            layer={layer}
            onChange={onAttributesChange}
            onClose={() => onAttributes?.(layer.id)}
          />
        </div>
      )}
    </div>
  )
}
