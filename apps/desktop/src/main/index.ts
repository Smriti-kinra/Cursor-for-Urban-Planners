import { app, BrowserWindow, ipcMain, dialog, shell, protocol, net } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'

const BACKEND_PORT = 8765
const isDev = !app.isPackaged

// Must be called before app.whenReady()
protocol.registerSchemesAsPrivileged([
  { scheme: 'localfile', privileges: { secure: true, bypassCSP: true, stream: true, supportFetchAPI: true } },
])

// Workspace persistence
const LAST_WORKSPACE_PATH = path.join(
  isDev ? path.resolve(process.cwd(), '.tmp') : app.getPath('userData'),
  'last-workspace.json'
)

function readLastWorkspace(): string | null {
  try { return JSON.parse(fs.readFileSync(LAST_WORKSPACE_PATH, 'utf-8')).path || null } catch { return null }
}
function writeLastWorkspace(p: string | null): void {
  try {
    fs.mkdirSync(path.dirname(LAST_WORKSPACE_PATH), { recursive: true })
    fs.writeFileSync(LAST_WORKSPACE_PATH, JSON.stringify({ path: p }))
  } catch { /* ignore */ }
}

interface ModelConfig {
  id: string
  name: string
  provider: 'openai' | 'anthropic' | 'google'
  locked: boolean
}

const ALL_MODELS: ModelConfig[] = [
  { id: 'gpt-5.4-nano', name: 'GPT-5.4 Nano', provider: 'openai', locked: false },
]

const DEFAULT_MODEL = 'gpt-5.4-nano'

// Store selected model in backend dir so Python can read it too
const MODEL_CONFIG_PATH = isDev
  ? path.resolve(process.cwd(), 'packages/backend/model_config.json')
  : path.join(process.resourcesPath, 'backend', 'model_config.json')

function readCurrentModel(): string {
  try {
    const config = JSON.parse(fs.readFileSync(MODEL_CONFIG_PATH, 'utf-8'))
    return config.model || DEFAULT_MODEL
  } catch {
    return DEFAULT_MODEL
  }
}

function writeCurrentModel(model: string): void {
  try {
    fs.writeFileSync(MODEL_CONFIG_PATH, JSON.stringify({ model }, null, 2))
  } catch {
    /* ignore write errors */
  }
}

let mainWindow: BrowserWindow | null = null
let backendProcess: ChildProcess | null = null
let allowMainWindowClose = false
let quitFlushTimer: ReturnType<typeof setTimeout> | null = null

function startBackend(): void {
  if (isDev) return

  const backendBinary = process.platform === 'win32' ? 'backend.exe' : 'backend'
  const backendPath = path.join(process.resourcesPath, 'backend', backendBinary)

  backendProcess = spawn(backendPath, ['--port', String(BACKEND_PORT)], {
    stdio: ['ignore', 'pipe', 'pipe']
  })

  backendProcess.stdout?.on('data', (d) => console.log(`[backend] ${d}`))
  backendProcess.stderr?.on('data', (d) => console.error(`[backend] ${d}`))
  backendProcess.on('exit', (code) => console.log(`[backend] exited ${code}`))
}

function stopBackend(): void {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
}

async function waitForBackend(retries = 30, delay = 500): Promise<boolean> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${BACKEND_PORT}/health`)
      if (res.ok) return true
    } catch {
      /* not ready yet */
    }
    await new Promise((r) => setTimeout(r, delay))
  }
  return false
}

// ── Model switching IPC ────────────────────────────────────────────────────────

// Workspace persistence IPC
ipcMain.handle('get-last-workspace', () => readLastWorkspace())
ipcMain.handle('set-last-workspace', (_e, p: string | null) => writeLastWorkspace(p))

// Open file dialog (for document mode)
ipcMain.handle('open-file', async (_e, opts: { filters?: { name: string; extensions: string[] }[] }) => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ['openFile'],
    filters: opts?.filters || [{ name: 'All Files', extensions: ['*'] }],
  })
  return result.canceled ? null : result.filePaths[0] ?? null
})

// Read file as base64 (for sending images to AI vision)
ipcMain.handle('read-file-base64', async (_e, filePath: string) => {
  try { return fs.readFileSync(filePath).toString('base64') } catch { return null }
})

ipcMain.handle('get-models', () => ALL_MODELS)

ipcMain.handle('get-current-model', () => readCurrentModel())

ipcMain.handle('switch-model', async (_event, newModel: string) => {
  writeCurrentModel(newModel)
  return { ok: true, requiresManualRestart: false }
})

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#1e1e2e',
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  if (isDev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  mainWindow.on('close', (e) => {
    if (allowMainWindowClose || !mainWindow) return
    if (mainWindow.webContents.isLoading()) {
      allowMainWindowClose = true
      return
    }
    e.preventDefault()
    if (quitFlushTimer) clearTimeout(quitFlushTimer)
    quitFlushTimer = setTimeout(() => {
      quitFlushTimer = null
      allowMainWindowClose = true
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close()
      allowMainWindowClose = false
    }, 4000)
    mainWindow.webContents.send('app-before-quit')
  })
}

ipcMain.on('app-quit-flush-done', () => {
  if (quitFlushTimer) {
    clearTimeout(quitFlushTimer)
    quitFlushTimer = null
  }
  allowMainWindowClose = true
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.close()
  }
  allowMainWindowClose = false
})

// --- IPC Handlers ---

ipcMain.handle('select-workspace', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ['openDirectory'],
    title: 'Select Workspace Folder'
  })
  if (result.canceled || result.filePaths.length === 0) return null
  const selected = result.filePaths[0]
  writeLastWorkspace(selected)
  return selected
})

ipcMain.handle('read-directory', async (_event, dirPath: string) => {
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true })
    return entries
      .filter((e) => !e.name.startsWith('.'))
      .sort((a, b) => {
        if (a.isDirectory() && !b.isDirectory()) return -1
        if (!a.isDirectory() && b.isDirectory()) return 1
        return a.name.localeCompare(b.name)
      })
      .map((e) => ({
        name: e.name,
        path: path.join(dirPath, e.name),
        isDirectory: e.isDirectory()
      }))
  } catch {
    return []
  }
})

ipcMain.handle('read-file', async (_event, filePath: string) => {
  try {
    return fs.readFileSync(filePath, 'utf-8')
  } catch {
    return null
  }
})

ipcMain.handle('write-file', async (_event, filePath: string, content: string) => {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    fs.writeFileSync(filePath, content, 'utf-8')
    return true
  } catch {
    return false
  }
})

// --- App lifecycle ---

app.whenReady().then(async () => {
  // Serve local files via localfile:// so the renderer can load them
  // regardless of whether it's running on file:// (prod) or http:// (dev).
  protocol.handle('localfile', (request) => {
    return net.fetch(request.url.replace(/^localfile:/, 'file:'))
  })

  startBackend()

  if (!isDev) {
    const backendReady = await waitForBackend()
    if (!backendReady) console.error('Backend failed to start')
  }

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  stopBackend()
})
