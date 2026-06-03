export interface ElectronAPI {
  getWorkerUrl: () => Promise<string>
  selectFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
  selectDirectory: () => Promise<string | null>
  openPath: (path: string) => Promise<string>
  getThirdPartyNoticesPath: () => Promise<string | null>
  openThirdPartyNotices: () => Promise<{ ok: boolean; path?: string; message?: string }>
  credentialSet: (service: string, account: string, password: string) => Promise<boolean>
  credentialGet: (service: string, account: string) => Promise<string | null>
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export {}
