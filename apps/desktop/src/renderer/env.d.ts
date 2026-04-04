export {}

declare global {
  interface FileEntry {
    name: string
    path: string
    isDirectory: boolean
  }

  interface ElectronAPI {
    selectWorkspace: () => Promise<string | null>
    readDirectory: (dirPath: string) => Promise<FileEntry[]>
    readFile: (filePath: string) => Promise<string | null>
    writeFile: (filePath: string, content: string) => Promise<boolean>
    /** Called when the user closes the window; flush saves, then main process closes. */
    onAppBeforeQuit: (handler: () => void | Promise<void>) => void
  }

  interface Window {
    electronAPI: ElectronAPI
  }
}
