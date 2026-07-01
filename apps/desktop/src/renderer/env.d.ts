export {}

declare global {
  interface FileEntry {
    name: string
    path: string
    isDirectory: boolean
  }

  interface ModelInfo {
    id: string
    name: string
    provider: 'openai' | 'anthropic' | 'google'
    locked: boolean
  }

  interface ElectronAPI {
    selectWorkspace: () => Promise<string | null>
    readDirectory: (dirPath: string) => Promise<FileEntry[]>
    readFile: (filePath: string) => Promise<string | null>
    writeFile: (filePath: string, content: string) => Promise<boolean>
    onAppBeforeQuit: (handler: () => void | Promise<void>) => void
    getLastWorkspace: () => Promise<string | null>
    setLastWorkspace: (path: string | null) => Promise<void>
    openFile: (opts: { filters?: { name: string; extensions: string[] }[] }) => Promise<string | null>
    readFileBase64: (filePath: string) => Promise<string | null>
    getModels: () => Promise<ModelInfo[]>
    getCurrentModel: () => Promise<string>
    switchModel: (model: string) => Promise<{ ok: boolean; requiresManualRestart: boolean }>
    importSpatialFiles: (workspacePath: string) => Promise<string[]>
    getAPIKey: () => Promise<string>
    setAPIKey: (key: string) => Promise<boolean>
  }

  interface Window {
    electronAPI: ElectronAPI
  }
}
