import { app, shell, BrowserWindow, ipcMain, dialog } from 'electron'
import { spawn, ChildProcessWithoutNullStreams } from 'child_process'
import { join } from 'path'
import { existsSync } from 'fs'

const WORKER_PORT = 8765
const WORKER_URL = `http://127.0.0.1:${WORKER_PORT}`

let mainWindow: BrowserWindow | null = null
let workerProcess: ChildProcessWithoutNullStreams | null = null
let workerKillTimer: ReturnType<typeof setTimeout> | null = null

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
    TC_STUDIO_PYTHON: resolvePythonExecutable()
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

function startWorker(): void {
  if (workerProcess) return

  const workerDir = getWorkerDir()
  const python = resolvePythonExecutable()
  workerProcess = spawn(
    python,
    ['-m', 'uvicorn', 'worker.main:app', '--host', '127.0.0.1', '--port', String(WORKER_PORT)],
    { cwd: workerDir, env: buildWorkerEnv() }
  )
  workerProcess.stdout.on('data', (d) => console.log('[worker]', d.toString()))
  workerProcess.stderr.on('data', (d) => console.error('[worker]', d.toString()))
  workerProcess.on('exit', () => {
    workerProcess = null
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

ipcMain.handle('select-file', async (_e, filters?: Electron.FileFilter[]) => {
  const result = await dialog.showOpenDialog(mainWindow!, { properties: ['openFile'], filters })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('select-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, { properties: ['openDirectory'] })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('open-path', async (_e, filePath: string) => shell.openPath(filePath))

ipcMain.handle('credential-set', async (_e, service: string, account: string, password: string) => {
  try {
    const keytar = await import('keytar')
    await keytar.setPassword(service, account, password)
    return true
  } catch {
    return false
  }
})

ipcMain.handle('credential-get', async (_e, service: string, account: string) => {
  try {
    const keytar = await import('keytar')
    return await keytar.getPassword(service, account)
  } catch {
    return null
  }
})
