export interface ElectronAPI {
  getWorkerUrl: () => Promise<string>
  selectFile: (filters?: { name: string; extensions: string[] }[]) => Promise<string | null>
  selectDirectory: () => Promise<string | null>
  openPath: (path: string) => Promise<string>
  getThirdPartyNoticesPath: () => Promise<string | null>
  openThirdPartyNotices: () => Promise<{ ok: boolean; path?: string; message?: string }>
  credentialSet: (
    service: string,
    account: string,
    password: string
  ) => Promise<{ ok: true } | { ok: false; message: string }>
  credentialGet: (
    service: string,
    account: string
  ) => Promise<{ ok: true; password: string } | { ok: false; message: string }>
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export {}
