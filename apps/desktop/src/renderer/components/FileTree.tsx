import { useState, useEffect, useCallback } from 'react'
import './FileTree.css'

interface FileTreeProps {
  workspacePath: string | null
}

interface TreeNodeProps {
  entry: FileEntry
  depth: number
}

function TreeNode({ entry, depth }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false)
  const [children, setChildren] = useState<FileEntry[]>([])

  const toggle = async (): Promise<void> => {
    if (!entry.isDirectory) return
    if (!expanded) {
      const items = await window.electronAPI.readDirectory(entry.path)
      setChildren(items)
    }
    setExpanded(!expanded)
  }

  return (
    <div className="tree-node">
      <div
        className={`tree-item ${entry.isDirectory ? 'directory' : 'file'}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={toggle}
      >
        <span className="tree-icon">
          {entry.isDirectory ? (expanded ? '▾' : '▸') : '·'}
        </span>
        <span className="tree-name">{entry.name}</span>
      </div>
      {expanded &&
        children.map((child) => (
          <TreeNode key={child.path} entry={child} depth={depth + 1} />
        ))}
    </div>
  )
}

export default function FileTree({ workspacePath }: FileTreeProps) {
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
    <div className="file-tree">
      {entries.map((entry) => (
        <TreeNode key={entry.path} entry={entry} depth={0} />
      ))}
    </div>
  )
}
