export {}

interface FileEntry {
  name: string
  path: string
  isDirectory: boolean
}

interface ElectronAPI {
  selectWorkspace: () => Promise<string | null>
  readDirectory: (dirPath: string) => Promise<FileEntry[]>
  readFile: (filePath: string) => Promise<string | null>
}

declare global {
  interface FileEntry {
    name: string
    path: string
    isDirectory: boolean
  }

  interface Window {
    electronAPI: ElectronAPI
  }
}
