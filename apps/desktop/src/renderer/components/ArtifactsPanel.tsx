import { useState, useEffect, useCallback } from 'react'
import './ArtifactsPanel.css'

const API_BASE = 'http://localhost:8765/api/artifacts'

interface Artifact {
  id: number
  title: string
  content: string
  artifact_type: string
  created_at: string
  updated_at: string
}

export default function ArtifactsPanel() {
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [artifactType, setArtifactType] = useState('note')

  const fetchArtifacts = useCallback(async () => {
    try {
      const res = await fetch(API_BASE)
      if (res.ok) {
        const data = await res.json()
        setArtifacts(data)
      }
    } catch {
      /* backend may not be available */
    }
  }, [])

  useEffect(() => {
    fetchArtifacts()
  }, [fetchArtifacts])

  const createArtifact = async (): Promise<void> => {
    if (!title.trim()) return
    try {
      const res = await fetch(API_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, artifact_type: artifactType })
      })
      if (res.ok) {
        setTitle('')
        setContent('')
        setShowForm(false)
        fetchArtifacts()
      }
    } catch {
      /* backend may not be available */
    }
  }

  const deleteArtifact = async (id: number): Promise<void> => {
    try {
      await fetch(`${API_BASE}/${id}`, { method: 'DELETE' })
      if (selectedId === id) setSelectedId(null)
      fetchArtifacts()
    } catch {
      /* backend may not be available */
    }
  }

  const selected = artifacts.find((a) => a.id === selectedId)

  return (
    <div className="artifacts-panel">
      <div className="artifacts-toolbar">
        <button className="new-artifact-btn" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ New'}
        </button>
        <button className="refresh-btn" onClick={fetchArtifacts}>
          &#8635;
        </button>
      </div>

      {showForm && (
        <div className="artifact-form">
          <input
            className="artifact-input"
            placeholder="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <select
            className="artifact-select"
            value={artifactType}
            onChange={(e) => setArtifactType(e.target.value)}
          >
            <option value="note">Note</option>
            <option value="analysis">Analysis</option>
            <option value="report">Report</option>
            <option value="sketch">Sketch</option>
          </select>
          <textarea
            className="artifact-textarea"
            placeholder="Content..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
          />
          <button className="save-btn" onClick={createArtifact}>
            Save
          </button>
        </div>
      )}

      <div className="artifacts-list">
        {artifacts.length === 0 && !showForm && (
          <div className="artifacts-empty">
            <p>No artifacts yet</p>
            <p className="hint">Save notes, analyses, and reports here.</p>
          </div>
        )}
        {artifacts.map((a) => (
          <div
            key={a.id}
            className={`artifact-item ${selectedId === a.id ? 'selected' : ''}`}
            onClick={() => setSelectedId(selectedId === a.id ? null : a.id)}
          >
            <div className="artifact-item-header">
              <span className="artifact-type-badge">{a.artifact_type}</span>
              <span className="artifact-title">{a.title}</span>
              <button
                className="delete-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  deleteArtifact(a.id)
                }}
              >
                &times;
              </button>
            </div>
            {selectedId === a.id && (
              <div className="artifact-detail">
                <p>{a.content}</p>
                <span className="artifact-date">
                  {new Date(a.created_at).toLocaleDateString()}
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
