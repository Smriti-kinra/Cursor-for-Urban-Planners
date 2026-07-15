import { MapBookmark } from '../types'
import './BookmarkPanel.css'

interface BookmarkPanelProps {
  bookmarks: MapBookmark[]
  onGoTo: (b: MapBookmark) => void
  onRemove: (id: string) => void
  onSaveCurrent: (name: string) => void
}

export default function BookmarkPanel({
  bookmarks,
  onGoTo,
  onRemove,
  onSaveCurrent,
}: BookmarkPanelProps) {
  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = e.currentTarget
    const input = form.elements.namedItem('bname') as HTMLInputElement
    const name = input?.value?.trim()
    if (name) {
      onSaveCurrent(name)
      input.value = ''
    }
  }

  return (
    <div className="bookmark-panel">
      <form className="bookmark-add" onSubmit={handleSubmit}>
        <input
          name="bname"
          type="text"
          placeholder="Save current map view as…"
          className="bookmark-input"
        />
        <button type="submit" className="bookmark-save-btn" title="Save bookmark">
          Save
        </button>
      </form>
      {bookmarks.length === 0 ? (
        <p className="bookmark-empty">No bookmarks yet. Pan/zoom, then save above or ask the assistant.</p>
      ) : (
        <ul className="bookmark-list">
          {bookmarks.map((b) => (
            <li key={b.id} className="bookmark-item">
              <button type="button" className="bookmark-go" onClick={() => onGoTo(b)} title="Fly here">
                {b.name}
              </button>
              <span className="bookmark-meta">
                z{b.zoom.toFixed(0)}
              </span>
              <button
                type="button"
                className="bookmark-del"
                onClick={() => onRemove(b.id)}
                title="Remove"
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
