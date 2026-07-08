import { useState, useEffect, useCallback } from 'react'
import './FileTree.css'

interface FileTreeProps {
  workspacePath: string | null
  onFileClick?: (entry: FileEntry) => void
  onImportClick?: () => void
  revision?: number
}

interface TreeNodeProps {
  entry: FileEntry
  depth: number
  onFileClick?: (entry: FileEntry) => void
}

function TreeNode({ entry, depth, onFileClick }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false)
  const [children, setChildren] = useState<FileEntry[]>([])

  const toggle = async (): Promise<void> => {
    if (entry.isDirectory) {
      if (!expanded) {
        const items = await window.electronAPI.readDirectory(entry.path)
        const filtered = items.filter(
          (item) => !['project.json', 'google-maps-key.json', 'api-key.json'].includes(item.name.toLowerCase())
        )
        setChildren(filtered)
      }
      setExpanded(!expanded)
    } else if (onFileClick) {
      onFileClick(entry)
    }
  }

  const lower = entry.name.toLowerCase()
  const isGeoJSON = !entry.isDirectory && (lower.endsWith('.geojson') || lower.endsWith('.json'))
  // Vector formats that need backend conversion before they become a layer.
  const isConvertible =
    !entry.isDirectory &&
    /\.(shp|gpkg|kml|kmz|gpx|csv)$/.test(lower)
  const isGeoFile = isGeoJSON || isConvertible

  return (
    <div className="tree-node">
      <div
        className={`tree-item ${entry.isDirectory ? 'directory' : 'file'} ${isGeoFile ? 'geojson' : ''}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={toggle}
      >
        <span className="tree-icon">
          {entry.isDirectory ? (expanded ? '▾' : '▸') : isGeoFile ? '◈' : '·'}
        </span>
        <span className="tree-name">{entry.name}</span>
      </div>
      {expanded &&
        children.map((child) => (
          <TreeNode key={child.path} entry={child} depth={depth + 1} onFileClick={onFileClick} />
        ))}
    </div>
  )
}

export default function FileTree({ workspacePath, onFileClick, onImportClick, revision }: FileTreeProps) {
  const [entries, setEntries] = useState<FileEntry[]>([])

  const loadDirectory = useCallback(async () => {
    if (!workspacePath) return
    const items = await window.electronAPI.readDirectory(workspacePath)
    const filtered = items.filter(
      (item) => !['project.json', 'google-maps-key.json', 'api-key.json'].includes(item.name.toLowerCase())
    )
    setEntries(filtered)
  }, [workspacePath])

  useEffect(() => {
    loadDirectory()
  }, [loadDirectory, revision])

  if (!workspacePath) {
    return (
      <div className="file-tree-empty">
        <p>No workspace open</p>
        <p className="hint">Click &quot;Open Workspace&quot; above</p>
      </div>
    )
  }

  return (
    <div className="file-tree-wrap">
      <div className="file-tree-header-container">
        <div className="file-tree-toolbar">
          <span className="file-tree-path" title={workspacePath}>
            {workspacePath.split('/').pop()}
          </span>
          <div className="file-tree-actions">
            <button className="file-tree-import-btn" onClick={onImportClick} title="Import spatial files">
              📥 Import
            </button>
            <button className="file-tree-refresh" onClick={loadDirectory} title="Refresh file tree">
              ↻
            </button>
          </div>
        </div>
        <div className="file-formats-banner">
          Supported: KML, KMZ, SHP, GPKG, GPX, CSV, GeoJSON
        </div>
      </div>
      <div className="file-tree">
        {entries.map((entry) => (
          <TreeNode key={entry.path} entry={entry} depth={0} onFileClick={onFileClick} />
        ))}
      </div>
    </div>
  )
}
