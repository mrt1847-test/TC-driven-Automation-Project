export interface ElectronAPI {
  getWorkerUrl: () => Promise<string>
  getWorkerToken: () => Promise<string>
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
  ) => Promise<{ ok: true; hasCredential: true } | { ok: false; message: string }>
  testrailImport: (
    projectId: string,
    action: 'preview' | 'import',
    body: Record<string, unknown>
  ) => Promise<{ ok: true; cases: unknown } | { ok: false; message: string }>
  googleSheetsImport: (
    projectId: string,
    action: 'preview' | 'import',
    body: Record<string, unknown>
  ) => Promise<{ ok: true; cases: unknown } | { ok: false; message: string }>
  testrailExport: (
    projectId: string,
    executionId: string,
    preview: boolean
  ) => Promise<{ ok: true; result: unknown } | { ok: false; message: string }>
  googleSheetsExport: (
    projectId: string,
    executionId: string,
    preview: boolean
  ) => Promise<{ ok: true; result: unknown } | { ok: false; message: string }>
  providerModels: (
    provider: string
  ) => Promise<{ ok: true; provider: string; models: string[] } | { ok: false; provider: string; message: string }>
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export {}
