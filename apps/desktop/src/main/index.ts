import { app, shell, BrowserWindow, ipcMain, dialog } from 'electron'
import { spawn, ChildProcessWithoutNullStreams } from 'child_process'
import { join } from 'path'
import { existsSync } from 'fs'

const WORKER_PORT = 8765
const WORKER_URL = `http://127.0.0.1:${WORKER_PORT}`

let mainWindow: BrowserWindow | null = null
let workerProcess: ChildProcessWithoutNullStreams | null = null

function workerEntry(): string {
  const devPath = join(__dirname, '../../../worker/worker/main.py')
  if (existsSync(devPath)) return devPath
  return join(process.resourcesPath, 'worker', 'worker', 'main.py')
}

function startWorker(): void {
  const workerDir = join(__dirname, '../../../../worker')
  const python = process.env.PYTHON || 'python'
  workerProcess = spawn(
    python,
    ['-m', 'uvicorn', 'worker.main:app', '--host', '127.0.0.1', '--port', String(WORKER_PORT)],
    { cwd: workerDir, shell: process.platform === 'win32', env: { ...process.env, TC_STUDIO_DATA_DIR: join(app.getPath('userData'), 'data') } }
  )
  workerProcess.stdout.on('data', (d) => console.log('[worker]', d.toString()))
  workerProcess.stderr.on('data', (d) => console.error('[worker]', d.toString()))
}

function stopWorker(): void {
  if (workerProcess) {
    workerProcess.kill()
    workerProcess = null
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
