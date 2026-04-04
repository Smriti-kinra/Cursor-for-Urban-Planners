import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  selectWorkspace: () => ipcRenderer.invoke('select-workspace'),
  readDirectory: (dirPath: string) => ipcRenderer.invoke('read-directory', dirPath),
  readFile: (filePath: string) => ipcRenderer.invoke('read-file', filePath),
  writeFile: (filePath: string, content: string) =>
    ipcRenderer.invoke('write-file', filePath, content),
  onAppBeforeQuit: (handler: () => void | Promise<void>) => {
    ipcRenderer.removeAllListeners('app-before-quit')
    ipcRenderer.on('app-before-quit', async () => {
      try {
        await handler()
      } finally {
        ipcRenderer.send('app-quit-flush-done')
      }
    })
  },
})
