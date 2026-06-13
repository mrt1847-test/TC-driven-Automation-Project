import { app, shell, BrowserWindow, ipcMain, dialog } from 'electron'
import { spawn, ChildProcessWithoutNullStreams } from 'child_process'
import { randomBytes } from 'crypto'
import { join } from 'path'
import { existsSync } from 'fs'
import { getCredential, setCredential } from './credentials'
import { listProviderModels } from './providerModels'

const WORKER_PORT = 8765
const WORKER_URL = `http://127.0.0.1:${WORKER_PORT}`
const WORKER_TOKEN_HEADER = 'X-TC-Studio-Worker-Token'
const WORKER_TOKEN = process.env.TC_STUDIO_WORKER_TOKEN || randomBytes(32).toString('base64url')

let mainWindow: BrowserWindow | null = null
let workerProcess: ChildProcessWithoutNullStreams | null = null
let workerKillTimer: ReturnType<typeof setTimeout> | null = null

/** Packaged Windows apps often have no console; writing to stdout/stderr then throws EPIPE. */
function safeWrite(stream: NodeJS.WriteStream, text: string): void {
  try {
    if (!stream.writable || stream.destroyed) return
    stream.write(text)
  } catch (error) {
    const code = (error as NodeJS.ErrnoException)?.code
    if (code !== 'EPIPE' && code !== 'ERR_STREAM_DESTROYED') {
      throw error
    }
  }
}

function logWorkerChunk(kind: 'stdout' | 'stderr', chunk: Buffer | string): void {
  const text = typeof chunk === 'string' ? chunk : chunk.toString()
  const line = `[worker] ${text}`
  if (kind === 'stderr') {
    safeWrite(process.stderr, line)
  } else {
    safeWrite(process.stdout, line)
  }
}

function detachWorkerStreamHandlers(proc: ChildProcessWithoutNullStreams): void {
  proc.stdout?.removeAllListeners('data')
  proc.stderr?.removeAllListeners('data')
}

function getWorkerDir(): string {
  const devWorkerDir = join(__dirname, '../../../worker')
  if (existsSync(join(devWorkerDir, 'worker', 'main.py'))) return devWorkerDir
  return join(process.resourcesPath, 'worker')
}

function getBundledRuntimeRoot(): string | null {
  const packaged = join(process.resourcesPath, 'runtime')
  if (existsSync(packaged)) return packaged
  const devStaging = join(__dirname, '../../../runtime-staging')
  if (existsSync(devStaging)) return devStaging
  return null
}

function resolvePythonExecutable(): string {
  const runtimeRoot = getBundledRuntimeRoot()
  if (runtimeRoot) {
    const winPython = join(runtimeRoot, 'python', 'python.exe')
    if (existsSync(winPython)) return winPython
    const unixPython = join(runtimeRoot, 'python', 'bin', 'python3')
    if (existsSync(unixPython)) return unixPython
  }
  return process.env.PYTHON || 'python'
}

function buildWorkerEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    TC_STUDIO_DATA_DIR: join(app.getPath('userData'), 'data'),
    TC_STUDIO_PYTHON: resolvePythonExecutable(),
    TC_STUDIO_WORKER_TOKEN: WORKER_TOKEN,
    TC_STUDIO_ALLOWED_ORIGINS: buildAllowedWorkerOrigins(),
    PYTHONUTF8: process.env.PYTHONUTF8 ?? '1',
    PYTHONIOENCODING: process.env.PYTHONIOENCODING ?? 'utf-8'
  }
  const runtimeRoot = getBundledRuntimeRoot()
  if (runtimeRoot) {
    env.TC_STUDIO_RESOURCES = runtimeRoot
    env.TC_STUDIO_RUNTIME_MODE = 'bundled'
    const browsers = join(runtimeRoot, 'ms-playwright')
    if (existsSync(browsers)) {
      env.TC_STUDIO_PLAYWRIGHT_BROWSERS_PATH = browsers
      env.PLAYWRIGHT_BROWSERS_PATH = browsers
    }
  } else {
    env.TC_STUDIO_RUNTIME_MODE = 'custom'
  }
  return env
}

function buildAllowedWorkerOrigins(): string {
  const origins = new Set([
    'http://127.0.0.1:5173',
    'http://localhost:5173',
    'http://127.0.0.1:8765',
    'http://localhost:8765',
    'file://',
    'null'
  ])
  for (const origin of (process.env.TC_STUDIO_ALLOWED_ORIGINS || '').split(',')) {
    const trimmed = origin.trim()
    if (trimmed) origins.add(trimmed)
  }
  if (process.env.ELECTRON_RENDERER_URL) {
    try {
      origins.add(new URL(process.env.ELECTRON_RENDERER_URL).origin)
    } catch {
      safeWrite(process.stderr, '[worker] Ignoring invalid ELECTRON_RENDERER_URL for CORS origins.\n')
    }
  }
  return Array.from(origins).join(',')
}

function startWorker(): void {
  if (workerProcess) return

  const workerDir = getWorkerDir()
  const python = resolvePythonExecutable()
  const proc = spawn(
    python,
    ['-m', 'uvicorn', 'worker.main:app', '--host', '127.0.0.1', '--port', String(WORKER_PORT)],
    { cwd: workerDir, env: buildWorkerEnv() }
  )
  workerProcess = proc
  proc.stdout.on('data', (d) => logWorkerChunk('stdout', d))
  proc.stderr.on('data', (d) => logWorkerChunk('stderr', d))
  proc.on('exit', () => {
    detachWorkerStreamHandlers(proc)
    if (workerProcess === proc) {
      workerProcess = null
    }
    if (workerKillTimer) {
      clearTimeout(workerKillTimer)
      workerKillTimer = null
    }
  })
}

function stopWorker(): void {
  if (!workerProcess) return

  const processToStop = workerProcess
  workerProcess = null
  detachWorkerStreamHandlers(processToStop)
  processToStop.kill('SIGTERM')
  workerKillTimer = setTimeout(() => {
    if (processToStop.exitCode === null) {
      processToStop.kill('SIGKILL')
    }
    workerKillTimer = null
  }, 2000)
  if (typeof workerKillTimer.unref === 'function') {
    workerKillTimer.unref()
  }
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })
  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  startWorker()
  createWindow()
})

app.on('window-all-closed', () => {
  stopWorker()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => stopWorker())
app.on('will-quit', () => stopWorker())

ipcMain.handle('get-worker-url', () => WORKER_URL)
ipcMain.handle('get-worker-token', () => WORKER_TOKEN)

ipcMain.handle('select-file', async (_e, filters?: Electron.FileFilter[]) => {
  const result = await dialog.showOpenDialog(mainWindow!, { properties: ['openFile'], filters })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('select-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, { properties: ['openDirectory'] })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('open-path', async (_e, filePath: string) => shell.openPath(filePath))

function getThirdPartyNoticesPath(): string | null {
  const runtimeRoot = getBundledRuntimeRoot()
  if (!runtimeRoot) return null
  const notices = join(runtimeRoot, 'THIRD_PARTY_NOTICES.txt')
  return existsSync(notices) ? notices : null
}

ipcMain.handle('get-third-party-notices-path', () => getThirdPartyNoticesPath())

ipcMain.handle('open-third-party-notices', async () => {
  const noticesPath = getThirdPartyNoticesPath()
  if (!noticesPath) {
    return { ok: false, message: 'Third-party notices are available after prepare-runtime or in a bundled installer build.' }
  }
  const error = await shell.openPath(noticesPath)
  return error ? { ok: false, message: error } : { ok: true, path: noticesPath }
})

ipcMain.handle('credential-set', async (_e, service: string, account: string, password: string) => {
  const result = await setCredential(service, account, password)
  if (result.ok) {
    return { ok: true as const }
  }
  safeWrite(process.stderr, `[credential-set] ${result.message}\n`)
  return { ok: false as const, message: result.message }
})

ipcMain.handle('credential-get', async (_e, service: string, account: string) => {
  const result = await getCredential(service, account)
  if (result.ok) {
    return { ok: true as const, hasCredential: true as const }
  }
  return { ok: false as const, message: result.message }
})

async function workerGetJson(path: string): Promise<{ ok: true; data: unknown } | { ok: false; message: string }> {
  try {
    const response = await fetch(`${WORKER_URL}${path}`)
    if (!response.ok) {
      return { ok: false, message: await workerErrorMessage(response) }
    }
    return { ok: true, data: await response.json() }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return { ok: false, message }
  }
}

async function workerPostJson(
  path: string,
  body: unknown
): Promise<{ ok: true; data: unknown } | { ok: false; message: string }> {
  try {
    const response = await fetch(`${WORKER_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', [WORKER_TOKEN_HEADER]: WORKER_TOKEN },
      body: JSON.stringify(body)
    })
    if (!response.ok) {
      return { ok: false, message: await workerErrorMessage(response) }
    }
    return { ok: true, data: await response.json() }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return { ok: false, message }
  }
}

async function workerErrorMessage(response: Response): Promise<string> {
  const text = await response.text()
  if (!text) return response.statusText || `HTTP ${response.status}`
  try {
    const parsed = JSON.parse(text)
    const detail = parsed?.detail
    if (typeof detail === 'string' && detail.trim()) return detail.trim()
    if (detail) return JSON.stringify(detail)
    return JSON.stringify(parsed)
  } catch {
    return text
  }
}

ipcMain.handle('testrail-import', async (_e, projectId: string, action: 'preview' | 'import', body: Record<string, unknown>) => {
  const settingsResult = await workerGetJson('/settings')
  if (!settingsResult.ok) {
    return { ok: false as const, message: settingsResult.message }
  }
  const settings = settingsResult.data as { integrations?: { testrail?: Record<string, unknown> } }
  const integration = settings.integrations?.testrail || {}
  const baseUrl = typeof integration.baseUrl === 'string' ? integration.baseUrl : ''
  const username = typeof integration.username === 'string' ? integration.username : ''
  if (!baseUrl.trim() || !username.trim()) {
    return { ok: false as const, message: 'Configure TestRail base URL and username in Settings.' }
  }

  const credential = await getCredential('tc-studio', 'connector:testrail:apiToken')
  if (!credential.ok) {
    return { ok: false as const, message: 'Store a TestRail API token in Settings before importing.' }
  }

  const path = `/projects/${encodeURIComponent(projectId)}/cases/import/testrail${action === 'preview' ? '/preview' : ''}`
  const result = await workerPostJson(path, {
    ...body,
    baseUrl,
    username,
    apiToken: credential.password
  })
  if (!result.ok) {
    return { ok: false as const, message: result.message }
  }
  return { ok: true as const, cases: result.data }
})

ipcMain.handle('google-sheets-import', async (_e, projectId: string, action: 'preview' | 'import', body: Record<string, unknown>) => {
  const settingsResult = await workerGetJson('/settings')
  if (!settingsResult.ok) {
    return { ok: false as const, message: settingsResult.message }
  }
  const settings = settingsResult.data as { integrations?: { googleSheets?: Record<string, unknown> } }
  const integration = settings.integrations?.googleSheets || {}
  const defaultSpreadsheetId = typeof integration.spreadsheetId === 'string' ? integration.spreadsheetId : ''
  const spreadsheetId = typeof body.spreadsheet_id === 'string' && body.spreadsheet_id.trim()
    ? body.spreadsheet_id
    : defaultSpreadsheetId
  if (!spreadsheetId.trim()) {
    return { ok: false as const, message: 'Configure a Google Sheets spreadsheet ID in Import or Settings.' }
  }

  const credential = await getCredential('tc-studio', 'connector:googleSheets:serviceAccountJson')
  if (!credential.ok) {
    return { ok: false as const, message: 'Store Google Sheets credential JSON in Settings before importing.' }
  }

  const path = `/projects/${encodeURIComponent(projectId)}/cases/import/google-sheets${action === 'preview' ? '/preview' : ''}`
  const result = await workerPostJson(path, {
    ...body,
    spreadsheet_id: spreadsheetId,
    credentialJson: credential.password
  })
  if (!result.ok) {
    return { ok: false as const, message: result.message }
  }
  return { ok: true as const, cases: result.data }
})

ipcMain.handle('testrail-export', async (_e, projectId: string, executionId: string, preview: boolean) => {
  if (preview) {
    const previewResult = await workerPostJson(
      `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/export/testrail`,
      { preview: true }
    )
    if (!previewResult.ok) {
      return { ok: false as const, message: previewResult.message }
    }
    return { ok: true as const, result: previewResult.data }
  }

  const settingsResult = await workerGetJson('/settings')
  if (!settingsResult.ok) {
    return { ok: false as const, message: settingsResult.message }
  }
  const settings = settingsResult.data as { integrations?: { testrail?: Record<string, unknown> } }
  const integration = settings.integrations?.testrail || {}
  if (integration.enabled === false) {
    const mockResult = await workerPostJson(
      `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/export/testrail`,
      { preview: false, config: { mock: true } }
    )
    if (!mockResult.ok) {
      return { ok: false as const, message: mockResult.message }
    }
    return { ok: true as const, result: mockResult.data }
  }

  const credential = await getCredential('tc-studio', 'connector:testrail:apiToken')
  if (!credential.ok) {
    return { ok: false as const, message: 'Store a TestRail API token in Settings before exporting results.' }
  }
  const result = await workerPostJson(
    `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/export/testrail`,
    { preview: false, config: { apiToken: credential.password } }
  )
  if (!result.ok) {
    return { ok: false as const, message: result.message }
  }
  return { ok: true as const, result: result.data }
})

ipcMain.handle('google-sheets-export', async (_e, projectId: string, executionId: string, preview: boolean) => {
  if (preview) {
    const previewResult = await workerPostJson(
      `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/export/google-sheets`,
      { preview: true }
    )
    if (!previewResult.ok) {
      return { ok: false as const, message: previewResult.message }
    }
    return { ok: true as const, result: previewResult.data }
  }

  const settingsResult = await workerGetJson('/settings')
  if (!settingsResult.ok) {
    return { ok: false as const, message: settingsResult.message }
  }
  const settings = settingsResult.data as { integrations?: { googleSheets?: Record<string, unknown> } }
  const integration = settings.integrations?.googleSheets || {}
  if (integration.enabled !== true) {
    const mockResult = await workerPostJson(
      `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/export/google-sheets`,
      { preview: false, config: { mock: true } }
    )
    if (!mockResult.ok) {
      return { ok: false as const, message: mockResult.message }
    }
    return { ok: true as const, result: mockResult.data }
  }

  const credential = await getCredential('tc-studio', 'connector:googleSheets:serviceAccountJson')
  if (!credential.ok) {
    return { ok: false as const, message: 'Store Google Sheets credential JSON in Settings before exporting results.' }
  }
  const result = await workerPostJson(
    `/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(executionId)}/export/google-sheets`,
    { preview: false, config: { credentialJson: credential.password } }
  )
  if (!result.ok) {
    return { ok: false as const, message: result.message }
  }
  return { ok: true as const, result: result.data }
})

ipcMain.handle('provider-models', async (_e, provider: string) => {
  const credential = await getCredential('tc-studio', provider)
  if (!credential.ok) {
    return { ok: false as const, provider, message: credential.message }
  }
  return listProviderModels(provider, credential.password)
})
