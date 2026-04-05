import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'

const BACKEND_PORT = 8765
const OPENCODE_PORT = 4096
const OLLAMA_PORT = 11434
const isDev = !app.isPackaged

// opencode.json is in the project root (dev) or bundled resources (prod)
const OPENCODE_JSON_PATH = isDev
  ? path.resolve(process.cwd(), 'opencode.json')
  : path.join(process.resourcesPath, 'opencode.json')

interface ModelConfig {
  id: string
  name: string
  provider: 'ollama' | 'anthropic' | 'google'
  local: boolean
  envKey?: string
}

const ALL_MODELS: ModelConfig[] = [
  { id: 'ollama/qwen2.5:14b', name: 'Qwen 2.5 14B', provider: 'ollama', local: true },
  { id: 'ollama/llama3.1:8b', name: 'Llama 3.1 8B', provider: 'ollama', local: true },
  { id: 'anthropic/claude-sonnet-4-20250514', name: 'Claude Sonnet 4', provider: 'anthropic', local: false, envKey: 'ANTHROPIC_API_KEY' },
  { id: 'google/gemini-2.5-flash', name: 'Gemini 2.5 Flash', provider: 'google', local: false, envKey: 'GEMINI_API_KEY' },
]

function readOpencodeModel(): string {
  try {
    const config = JSON.parse(fs.readFileSync(OPENCODE_JSON_PATH, 'utf-8'))
    return config.model || 'ollama/qwen2.5:14b'
  } catch {
    return 'ollama/qwen2.5:14b'
  }
}

function writeOpencodeModel(model: string): void {
  const config = JSON.parse(fs.readFileSync(OPENCODE_JSON_PATH, 'utf-8'))
  config.model = model
  fs.writeFileSync(OPENCODE_JSON_PATH, JSON.stringify(config, null, 2))
}

let mainWindow: BrowserWindow | null = null
let backendProcess: ChildProcess | null = null
let ollamaProcess: ChildProcess | null = null
let opencodeProcess: ChildProcess | null = null
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

async function startOllama(): Promise<void> {
  // Check if Ollama is already running (common in dev)
  try {
    const res = await fetch(`http://localhost:${OLLAMA_PORT}/`)
    if (res.ok) {
      console.log('[ollama] already running, skipping spawn')
      return
    }
  } catch {
    /* not running yet */
  }

  ollamaProcess = spawn('ollama', ['serve'], {
    stdio: ['ignore', 'pipe', 'pipe']
  })

  ollamaProcess.stdout?.on('data', (d) => console.log(`[ollama] ${d}`))
  ollamaProcess.stderr?.on('data', (d) => console.error(`[ollama] ${d}`))
  ollamaProcess.on('exit', (code) => console.log(`[ollama] exited ${code}`))
}

async function waitForOllama(retries = 20, delay = 500): Promise<boolean> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`http://localhost:${OLLAMA_PORT}/`)
      if (res.ok) return true
    } catch {
      /* not ready yet */
    }
    await new Promise((r) => setTimeout(r, delay))
  }
  return false
}

function startOpencode(): void {
  if (isDev) return

  // opencode must be installed globally: npm install -g opencode-ai
  opencodeProcess = spawn('opencode', ['serve', '--port', String(OPENCODE_PORT)], {
    stdio: ['ignore', 'pipe', 'pipe'],
    cwd: process.resourcesPath,
  })

  opencodeProcess.stdout?.on('data', (d) => console.log(`[opencode] ${d}`))
  opencodeProcess.stderr?.on('data', (d) => console.error(`[opencode] ${d}`))
  opencodeProcess.on('exit', (code) => console.log(`[opencode] exited ${code}`))
}

function stopBackend(): void {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
  if (opencodeProcess) {
    opencodeProcess.kill()
    opencodeProcess = null
  }
  if (ollamaProcess) {
    ollamaProcess.kill()
    ollamaProcess = null
  }
}

async function waitForBackend(retries = 30, delay = 500): Promise<boolean> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`http://localhost:${BACKEND_PORT}/health`)
      if (res.ok) return true
    } catch {
      /* not ready yet */
    }
    await new Promise((r) => setTimeout(r, delay))
  }
  return false
}

async function waitForOpencode(retries = 20, delay = 500): Promise<boolean> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`http://localhost:${OPENCODE_PORT}/session`)
      if (res.ok) return true
    } catch {
      /* not ready yet */
    }
    await new Promise((r) => setTimeout(r, delay))
  }
  return false
}

// ── Model switching IPC ────────────────────────────────────────────────────────

ipcMain.handle('get-models', () =>
  ALL_MODELS.filter((m) => !m.envKey || process.env[m.envKey])
)

ipcMain.handle('get-current-model', () => readOpencodeModel())

ipcMain.handle('switch-model', async (_event, newModel: string) => {
  const oldModel = readOpencodeModel()

  // Unload the old Ollama model from VRAM before loading a new one
  if (oldModel.startsWith('ollama/')) {
    try {
      await fetch(`http://localhost:${OLLAMA_PORT}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: oldModel.replace('ollama/', ''), keep_alive: 0, prompt: '' }),
      })
    } catch { /* ignore — Ollama may not have the model loaded */ }
  }

  writeOpencodeModel(newModel)

  if (!isDev) {
    // Production: restart opencode so it picks up the new model
    if (opencodeProcess) {
      opencodeProcess.kill()
      opencodeProcess = null
    }
    await new Promise((r) => setTimeout(r, 600))
    startOpencode()
    await waitForOpencode()
    return { ok: true, requiresManualRestart: false }
  }

  // Dev: opencode was started manually — user must restart it
  return { ok: true, requiresManualRestart: true }
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
  return result.filePaths[0]
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
  startBackend()
  await startOllama()

  if (!isDev) {
    const [backendReady, ollamaReady] = await Promise.all([
      waitForBackend(),
      waitForOllama()
    ])
    if (!backendReady) console.error('Backend failed to start')
    if (!ollamaReady) console.error('Ollama failed to start — local model unavailable')
  }

  startOpencode()
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
