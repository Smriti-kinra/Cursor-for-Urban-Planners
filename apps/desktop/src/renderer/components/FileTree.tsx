import { useState, useEffect, useCallback } from 'react'
import './FileTree.css'

interface FileTreeProps {
  workspacePath: string | null
  onFileClick?: (entry: FileEntry) => void
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
        setChildren(items)
      }
      setExpanded(!expanded)
    } else if (onFileClick) {
      onFileClick(entry)
    }
  }

  const isGeoJSON = !entry.isDirectory && entry.name.toLowerCase().endsWith('.geojson')

  return (
    <div className="tree-node">
      <div
        className={`tree-item ${entry.isDirectory ? 'directory' : 'file'} ${isGeoJSON ? 'geojson' : ''}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={toggle}
      >
        <span className="tree-icon">
          {entry.isDirectory ? (expanded ? '▾' : '▸') : isGeoJSON ? '◈' : '·'}
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

export default function FileTree({ workspacePath, onFileClick }: FileTreeProps) {
  const [entries, setEntries] = useState<FileEntry[]>([])

  const loadDirectory = useCallback(async () => {
    if (!workspacePath) return
    const items = await window.electronAPI.readDirectory(workspacePath)
    setEntries(items)
  }, [workspacePath])

  useEffect(() => {
    loadDirectory()
  }, [loadDirectory])

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
      <div className="file-tree-toolbar">
        <span className="file-tree-path" title={workspacePath}>
          {workspacePath.split('/').pop()}
        </span>
        <button className="file-tree-refresh" onClick={loadDirectory} title="Refresh file tree">
          ↻
        </button>
      </div>
      <div className="file-tree">
        {entries.map((entry) => (
          <TreeNode key={entry.path} entry={entry} depth={0} onFileClick={onFileClick} />
        ))}
      </div>
    </div>
  )
}
