import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getWorkerUrl: () => ipcRenderer.invoke('get-worker-url'),
  selectFile: (filters?: Electron.FileFilter[]) => ipcRenderer.invoke('select-file', filters),
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  openPath: (path: string) => ipcRenderer.invoke('open-path', path),
  getThirdPartyNoticesPath: () => ipcRenderer.invoke('get-third-party-notices-path'),
  openThirdPartyNotices: () => ipcRenderer.invoke('open-third-party-notices'),
  credentialSet: (service: string, account: string, password: string) =>
    ipcRenderer.invoke('credential-set', service, account, password),
  credentialGet: (service: string, account: string) => ipcRenderer.invoke('credential-get', service, account),
  providerModels: (provider: string) => ipcRenderer.invoke('provider-models', provider)
})
