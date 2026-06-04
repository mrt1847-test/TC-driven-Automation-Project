let baseUrl = 'http://127.0.0.1:8765'

export async function initApiBase(): Promise<string> {
  if (window.electronAPI) {
    baseUrl = await window.electronAPI.getWorkerUrl()
  }
  return baseUrl
}

export function getBaseUrl(): string {
  return baseUrl
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) },
    ...options
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json()
}

export const api = {
  health: () => request<{ allOk: boolean }>('/health'),
  settings: {
    get: () => request<Record<string, unknown>>('/settings'),
    update: (body: unknown) => request('/settings', { method: 'PUT', body: JSON.stringify(body) }),
    validate: () => request('/settings/validate', { method: 'POST' })
  },
  projects: {
    list: () => request<Project[]>('/projects'),
    create: (body: { name: string; rootPath?: string }) =>
      request<Project>('/projects', { method: 'POST', body: JSON.stringify(body) }),
    get: (id: string) => request<Project>(`/projects/${id}`),
    delete: (id: string) => request(`/projects/${id}`, { method: 'DELETE' })
  },
  cases: {
    list: (projectId: string) => request<TestCase[]>(`/projects/${projectId}/cases`),
    get: (projectId: string, caseId: string) => request<NormalizedTestCase>(`/projects/${projectId}/cases/${caseId}`),
    patch: (projectId: string, caseId: string, body: { startUrl?: string; status?: string }) =>
      request<NormalizedTestCase>(`/projects/${projectId}/cases/${caseId}`, {
        method: 'PATCH',
        body: JSON.stringify(body)
      }),
    previewExcel: (projectId: string, body: unknown) =>
      request(`/projects/${projectId}/cases/import/excel/preview`, { method: 'POST', body: JSON.stringify(body) }),
    importExcel: (projectId: string, body: unknown) =>
      request(`/projects/${projectId}/cases/import/excel`, { method: 'POST', body: JSON.stringify(body) }),
    previewTestrailClone: (projectId: string, body: unknown) =>
      request<NormalizedTestCase[]>(`/projects/${projectId}/cases/import/testrail-clone/preview`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    importTestrailClone: (projectId: string, body: unknown) =>
      request<NormalizedTestCase[]>(`/projects/${projectId}/cases/import/testrail-clone`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    previewTestrail: (projectId: string, body: unknown) =>
      request<NormalizedTestCase[]>(`/projects/${projectId}/cases/import/testrail`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    previewGoogleSheets: (projectId: string, body: unknown) =>
      request<NormalizedTestCase[]>(`/projects/${projectId}/cases/import/google-sheets`, {
        method: 'POST',
        body: JSON.stringify(body)
      })
  },
  webwright: {
    list: (projectId: string) => request<WebwrightRun[]>(`/projects/${projectId}/webwright-runs`),
    run: (projectId: string, body: { caseIds: string[] }) =>
      request<JobResponse>(`/projects/${projectId}/webwright-runs`, { method: 'POST', body: JSON.stringify(body) }),
    retry: (projectId: string, runId: string) =>
      request<JobResponse>(`/projects/${projectId}/webwright-runs/${runId}/retry`, { method: 'POST' }),
    cancel: (projectId: string, runId: string) =>
      request<WebwrightRun>(`/projects/${projectId}/webwright-runs/${runId}/cancel`, { method: 'POST' })
  },
  mapping: {
    actions: (projectId: string, caseId: string) =>
      request(`/projects/${projectId}/cases/${caseId}/actions`),
    get: (projectId: string, caseId: string) =>
      request(`/projects/${projectId}/cases/${caseId}/mappings`),
    save: (projectId: string, caseId: string, body: unknown) =>
      request(`/projects/${projectId}/cases/${caseId}/mappings`, { method: 'PUT', body: JSON.stringify(body) }),
    normalize: (projectId: string, caseId: string) =>
      request(`/projects/${projectId}/cases/${caseId}/normalize`, { method: 'POST' })
  },
  generation: {
    generate: (projectId: string, body?: unknown) =>
      request(`/projects/${projectId}/generate`, { method: 'POST', body: JSON.stringify(body || {}) }),
    files: (projectId: string) => request<{ path: string; type: string }[]>(`/projects/${projectId}/generated-files`),
    content: (projectId: string, path: string) =>
      request<{ content: string }>(`/projects/${projectId}/generated-files/content?path=${encodeURIComponent(path)}`),
    save: (projectId: string, path: string, content: string) =>
      request(`/projects/${projectId}/generated-files/content`, {
        method: 'PUT',
        body: JSON.stringify({ path, content })
      }),
    search: (projectId: string, q: string) =>
      request(`/projects/${projectId}/search?q=${encodeURIComponent(q)}`)
  },
  executions: {
    list: (projectId: string) => request<ExecutionRun[]>(`/projects/${projectId}/executions`),
    run: (projectId: string, body: unknown) =>
      request<JobResponse>(`/projects/${projectId}/executions`, { method: 'POST', body: JSON.stringify(body) }),
    get: (projectId: string, id: string) => request<ExecutionDetail>(`/projects/${projectId}/executions/${id}`),
    rerunFailed: (projectId: string, id: string) =>
      request<JobResponse>(`/projects/${projectId}/executions/${id}/rerun-failed`, { method: 'POST' }),
    export: (projectId: string, id: string, target: string, preview = false) =>
      request(`/projects/${projectId}/executions/${id}/export/${target}`, {
        method: 'POST',
        body: JSON.stringify({ preview })
      })
  },
  projectHealth: (projectId: string, generatedPath: string) =>
    request(`/projects/${projectId}/health?generated_path=${encodeURIComponent(generatedPath)}`, { method: 'POST' }),
  installDeps: (projectId: string, generatedPath: string) =>
    request(`/projects/${projectId}/install-dependencies?generated_path=${encodeURIComponent(generatedPath)}`, {
      method: 'POST'
    })
}

export interface Project {
  id: string
  name: string
  root_path: string
  generated_project_path?: string
  default_env: string
}

export interface TestCase {
  id: string
  project_id: string
  title: string
  automation_key: string
  source_type: string
  source_case_id: string
  status: string
  priority?: string | null
  start_url?: string | null
  steps_json?: string
  expected_result?: string | null
}

export interface NormalizedTestCase {
  id: string
  source_type: string
  source_id: string
  title: string
  preconditions: string[]
  steps: { index: number; action: string; expected?: string | null }[]
  expected_result?: string | null
  automation_key: string
  priority?: string | null
  start_url?: string | null
  status: string
}

export interface WebwrightRun {
  id: string
  test_case_id: string
  automation_key: string
  status: string
  output_path?: string
  final_script_path?: string
  trajectory_path?: string
  error_message?: string
  started_at?: string | null
  ended_at?: string | null
}

export interface JobResponse {
  jobId: string
  status: string
  caseIds?: string[]
}

export interface ExecutionRun {
  id: string
  run_id: string
  env: string
  browser: string
  status: string
  result_path?: string
  started_at?: string | null
  ended_at?: string | null
  created_at?: string
}

export interface ExecutionResult {
  id: string
  execution_run_id: string
  automation_key: string
  source_type?: string | null
  source_case_id?: string | null
  title?: string | null
  status: string
  duration_ms?: number | null
  error?: string | null
  screenshot_path?: string | null
  trace_path?: string | null
}

export interface ExecutionDetail {
  run: ExecutionRun
  results: ExecutionResult[]
  summary?: {
    cases?: Array<{
      automationKey?: string
      automation_key?: string
      title?: string
      status: string
      error?: string | null
      artifacts?: {
        screenshot?: string | null
        trace?: string | null
      }
    }>
    summary?: Record<string, number>
  } | null
}

export type LogStreamStatus = 'connecting' | 'open' | 'closed' | 'error'

export function connectLogStream(
  jobId: string,
  onMessage: (msg: string) => void,
  onStatus?: (status: LogStreamStatus) => void
): WebSocket {
  onStatus?.('connecting')
  const ws = new WebSocket(`${baseUrl.replace('http', 'ws')}/ws/logs/${jobId}`)
  ws.onopen = () => onStatus?.('open')
  ws.onmessage = (e) => onMessage(String(e.data))
  ws.onerror = () => onStatus?.('error')
  ws.onclose = () => onStatus?.('closed')
  return ws
}
