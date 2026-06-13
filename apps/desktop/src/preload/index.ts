import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getWorkerUrl: () => ipcRenderer.invoke('get-worker-url'),
  getWorkerToken: () => ipcRenderer.invoke('get-worker-token'),
  selectFile: (filters?: Electron.FileFilter[]) => ipcRenderer.invoke('select-file', filters),
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  openPath: (path: string) => ipcRenderer.invoke('open-path', path),
  getThirdPartyNoticesPath: () => ipcRenderer.invoke('get-third-party-notices-path'),
  openThirdPartyNotices: () => ipcRenderer.invoke('open-third-party-notices'),
  credentialSet: (service: string, account: string, password: string) =>
    ipcRenderer.invoke('credential-set', service, account, password),
  credentialGet: (service: string, account: string) => ipcRenderer.invoke('credential-get', service, account),
  testrailImport: (projectId: string, action: 'preview' | 'import', body: Record<string, unknown>) =>
    ipcRenderer.invoke('testrail-import', projectId, action, body),
  googleSheetsImport: (projectId: string, action: 'preview' | 'import', body: Record<string, unknown>) =>
    ipcRenderer.invoke('google-sheets-import', projectId, action, body),
  testrailExport: (projectId: string, executionId: string, preview: boolean) =>
    ipcRenderer.invoke('testrail-export', projectId, executionId, preview),
  googleSheetsExport: (projectId: string, executionId: string, preview: boolean) =>
    ipcRenderer.invoke('google-sheets-export', projectId, executionId, preview),
  providerModels: (provider: string) => ipcRenderer.invoke('provider-models', provider)
})
