export interface ElectronAPI {
  getWorkerUrl: () => Promise<string>
  selectFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
  selectDirectory: () => Promise<string | null>
  openPath: (path: string) => Promise<string>
  credentialSet: (service: string, account: string, password: string) => Promise<boolean>
  credentialGet: (service: string, account: string) => Promise<string | null>
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export {}
