import { useState } from 'react'
import MapView from './components/MapView'
import FileTree from './components/FileTree'
import ChatPanel from './components/ChatPanel'
import ArtifactsPanel from './components/ArtifactsPanel'

type RightTab = 'chat' | 'artifacts'

function App() {
  const [workspacePath, setWorkspacePath] = useState<string | null>(null)
  const [activeRightTab, setActiveRightTab] = useState<RightTab>('chat')

  const handleSelectWorkspace = async (): Promise<void> => {
    const selected = await window.electronAPI.selectWorkspace()
    if (selected) setWorkspacePath(selected)
  }

  const workspaceLabel = workspacePath ? workspacePath.split('/').pop() : 'Open Workspace'

  return (
    <div className="app">
      <header className="titlebar">
        <div className="titlebar-drag" />
        <span className="titlebar-text">Cursor for Urban Planners</span>
        <button className="workspace-btn" onClick={handleSelectWorkspace}>
          {workspaceLabel}
        </button>
      </header>

      <div className="layout">
        <aside className="panel left-panel">
          <div className="panel-header">Files</div>
          <FileTree workspacePath={workspacePath} />
        </aside>

        <main className="center-panel">
          <MapView />
        </main>

        <aside className="panel right-panel">
          <div className="tab-bar">
            <button
              className={`tab ${activeRightTab === 'chat' ? 'active' : ''}`}
              onClick={() => setActiveRightTab('chat')}
            >
              Chat
            </button>
            <button
              className={`tab ${activeRightTab === 'artifacts' ? 'active' : ''}`}
              onClick={() => setActiveRightTab('artifacts')}
            >
              Artifacts
            </button>
          </div>
          {activeRightTab === 'chat' ? <ChatPanel /> : <ArtifactsPanel />}
        </aside>
      </div>
    </div>
  )
}

export default App
