let baseUrl = 'http://127.0.0.1:8765'
let workerToken = import.meta.env.VITE_TC_STUDIO_WORKER_TOKEN || ''
const WORKER_TOKEN_HEADER = 'X-TC-Studio-Worker-Token'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export async function initApiBase(): Promise<string> {
  if (window.electronAPI) {
    baseUrl = await window.electronAPI.getWorkerUrl()
    workerToken = await window.electronAPI.getWorkerToken()
  }
  return baseUrl
}

export function getBaseUrl(): string {
  return baseUrl
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (workerToken) headers.set(WORKER_TOKEN_HEADER, workerToken)
  const res = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers
  })
  if (!res.ok) {
    throw await buildApiError(res)
  }
  return res.json()
}

async function buildApiError(res: Response): Promise<ApiError> {
  const text = await res.text()
  const detail = parseResponseDetail(text)
  const message = formatApiErrorMessage(detail, res.statusText || `HTTP ${res.status}`)
  return new ApiError(message, res.status, detail)
}

function parseResponseDetail(text: string): unknown {
  if (!text) return null
  try {
    const parsed = JSON.parse(text)
    if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
      return (parsed as { detail: unknown }).detail
    }
    return parsed
  } catch {
    return text
  }
}

function formatApiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (Array.isArray(detail)) {
    const messages = detail.map(formatValidationItem).filter(Boolean)
    if (messages.length) return messages.join('; ')
  }
  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>
    const message = record.message || record.error || record.reason
    if (typeof message === 'string' && message.trim()) return message.trim()
    try {
      return JSON.stringify(detail)
    } catch {
      return fallback
    }
  }
  return fallback
}

function formatValidationItem(item: unknown): string {
  if (!item || typeof item !== 'object') return typeof item === 'string' ? item : ''
  const record = item as Record<string, unknown>
  const loc = Array.isArray(record.loc) ? record.loc.join('.') : ''
  const message = typeof record.msg === 'string' ? record.msg : ''
  if (loc && message) return `${loc}: ${message}`
  return message || loc
}

export function getApiErrorMessage(error: unknown, fallback = 'Request failed.'): string {
  return error instanceof Error && error.message ? error.message : fallback
}

export type GenerationConflictDetail = {
  message?: string
  editedFiles?: string[]
  staleFiles?: string[]
  conflictFiles?: string[]
  affectedFiles?: string[]
  changedFiles?: string[]
  preservedFiles?: string[]
}

export function getGenerationConflictDetail(error: unknown): GenerationConflictDetail | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = error.detail
  if (!detail || typeof detail !== 'object') return null
  const record = detail as Record<string, unknown>
  const editedFiles = Array.isArray(record.editedFiles) ? record.editedFiles as string[] : []
  const staleFiles = Array.isArray(record.staleFiles) ? record.staleFiles as string[] : []
  const conflictFiles = Array.isArray(record.conflictFiles) ? record.conflictFiles as string[] : []
  if (!editedFiles.length && !staleFiles.length && !conflictFiles.length) return null
  return {
    message: typeof record.message === 'string' ? record.message : undefined,
    editedFiles,
    staleFiles,
    conflictFiles,
    affectedFiles: Array.isArray(record.affectedFiles) ? record.affectedFiles as string[] : [],
    changedFiles: Array.isArray(record.changedFiles) ? record.changedFiles as string[] : [],
    preservedFiles: Array.isArray(record.preservedFiles) ? record.preservedFiles as string[] : [],
  }
}

export type ActionMutationRequest = {
  type?: string
  target?: string | null
  selector?: string | null
  value?: string | null
  source_line?: number | null
  order_index?: number | null
  insertAfterActionId?: string | null
  insert_after_action_id?: string | null
}

export const api = {
  health: () => request<{ allOk: boolean }>('/health'),
  settings: {
    get: () => request<Record<string, unknown>>('/settings'),
    update: (body: unknown) => request('/settings', { method: 'PUT', body: JSON.stringify(body) }),
    connectorCredentials: () => request<ConnectorCredentialsResponse>('/settings/connector-credentials'),
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
      request<NormalizedTestCase[]>(`/projects/${projectId}/cases/import/testrail/preview`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    importTestrail: (projectId: string, body: unknown) =>
      request<NormalizedTestCase[]>(`/projects/${projectId}/cases/import/testrail`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    previewGoogleSheets: (projectId: string, body: unknown) =>
      request<NormalizedTestCase[]>(`/projects/${projectId}/cases/import/google-sheets/preview`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    importGoogleSheets: (projectId: string, body: unknown) =>
      request<NormalizedTestCase[]>(`/projects/${projectId}/cases/import/google-sheets`, {
        method: 'POST',
        body: JSON.stringify(body)
      })
  },
  webwright: {
    list: (projectId: string) => request<WebwrightRun[]>(`/projects/${projectId}/webwright-runs`),
    run: (projectId: string, body: {
      caseIds: string[]
      presetId?: string | null
      modelConfig?: string
      environment?: string
      startUrlOverride?: string | null
    }) =>
      request<JobResponse>(`/projects/${projectId}/webwright-runs`, { method: 'POST', body: JSON.stringify(body) }),
    retry: (projectId: string, runId: string) =>
      request<JobResponse>(`/projects/${projectId}/webwright-runs/${runId}/retry`, { method: 'POST' }),
    cancel: (projectId: string, runId: string) =>
      request<WebwrightRun>(`/projects/${projectId}/webwright-runs/${runId}/cancel`, { method: 'POST' })
  },
  prompts: {
    composer: (projectId: string) =>
      request<PromptComposerResponse>(`/projects/${projectId}/prompt-composer`),
    saveComposer: (projectId: string, body: PromptComposerUpdateRequest) =>
      request<PromptComposerResponse>(`/projects/${projectId}/prompt-composer`, {
        method: 'PUT',
        body: JSON.stringify(body)
      }),
    presets: (projectId: string) =>
      request<PromptPresetsResponse>(`/projects/${projectId}/prompt-presets`),
    savePresets: (projectId: string, body: PromptPresetUpdateRequest) =>
      request<PromptPresetsResponse>(`/projects/${projectId}/prompt-presets`, {
        method: 'PUT',
        body: JSON.stringify(body)
      }),
    preview: (projectId: string, body: PromptPreviewRequest) =>
      request<PromptPreviewResponse>(`/projects/${projectId}/prompt-preview`, {
        method: 'POST',
        body: JSON.stringify(body)
      })
  },
  mapping: {
    actions: (projectId: string, caseId: string) =>
      request(`/projects/${projectId}/cases/${caseId}/actions`),
    createAction: (projectId: string, caseId: string, body: ActionMutationRequest) =>
      request(`/projects/${projectId}/cases/${caseId}/actions`, { method: 'POST', body: JSON.stringify(body) }),
    updateAction: (projectId: string, caseId: string, actionId: string, body: ActionMutationRequest) =>
      request(`/projects/${projectId}/cases/${caseId}/actions/${actionId}`, {
        method: 'PATCH',
        body: JSON.stringify(body)
      }),
    deleteAction: (projectId: string, caseId: string, actionId: string) =>
      request(`/projects/${projectId}/cases/${caseId}/actions/${actionId}`, { method: 'DELETE' }),
    insertStepAction: (projectId: string, caseId: string, stepIndex: number, body: ActionMutationRequest) =>
      request(`/projects/${projectId}/cases/${caseId}/steps/${stepIndex}/actions`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    updateStepAction: (
      projectId: string,
      caseId: string,
      stepIndex: number,
      actionId: string,
      body: ActionMutationRequest
    ) =>
      request(`/projects/${projectId}/cases/${caseId}/steps/${stepIndex}/actions/${actionId}`, {
        method: 'PATCH',
        body: JSON.stringify(body)
      }),
    get: (projectId: string, caseId: string) =>
      request(`/projects/${projectId}/cases/${caseId}/mappings`),
    save: (projectId: string, caseId: string, body: unknown) =>
      request(`/projects/${projectId}/cases/${caseId}/mappings`, { method: 'PUT', body: JSON.stringify(body) }),
    validateStructure: (projectId: string, caseId: string) =>
      request<StructureValidationResponse>(`/projects/${projectId}/cases/${caseId}/structure/validate`),
    normalize: (projectId: string, caseId: string) =>
      request(`/projects/${projectId}/cases/${caseId}/normalize`, { method: 'POST' })
  },
  generation: {
    generate: (projectId: string, body?: unknown) =>
      request(`/projects/${projectId}/generate`, { method: 'POST', body: JSON.stringify(body || {}) }),
    refreshWebwrightAndRegenerate: (projectId: string, caseId: string, body?: { modelConfig?: string }) =>
      request(`/projects/${projectId}/cases/${caseId}/refresh-webwright-and-regenerate`, {
        method: 'POST',
        body: JSON.stringify(body || {})
      }),
    previewRefreshWebwrightAndRegenerate: (projectId: string, caseId: string) =>
      request(`/projects/${projectId}/cases/${caseId}/refresh-webwright-and-regenerate/preview`, {
        method: 'POST',
        body: JSON.stringify({})
      }),
    generateSelected: (projectId: string, body: { caseIds: string[] }) =>
      request(`/projects/${projectId}/generate/selected`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    previewSelected: (projectId: string, body: { caseIds: string[] }) =>
      request(`/projects/${projectId}/generate/selected/preview`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
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
    diagnose: (projectId: string, id: string) =>
      request<ExecutionDiagnosis>(`/projects/${projectId}/executions/${id}/diagnose`, { method: 'POST' }),
    createHealingProposal: (projectId: string, id: string, executionResultId: string) =>
      request<HealingProposalActionResponse>(`/projects/${projectId}/executions/${id}/healing-proposals`, {
        method: 'POST',
        body: JSON.stringify({ executionResultId })
      }),
    retireResult: (
      projectId: string,
      id: string,
      resultId: string,
      body: { action?: 'retire' | 'delete'; caseId: string; confirmed: boolean }
    ) =>
      request(`/projects/${projectId}/executions/${id}/results/${resultId}/retire`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    previewRetireResult: (
      projectId: string,
      id: string,
      resultId: string,
      body: { action?: 'retire' | 'delete'; caseId: string }
    ) =>
      request(`/projects/${projectId}/executions/${id}/results/${resultId}/retire/preview`, {
        method: 'POST',
        body: JSON.stringify(body)
      }),
    rerunFailed: (projectId: string, id: string) =>
      request<JobResponse>(`/projects/${projectId}/executions/${id}/rerun-failed`, { method: 'POST' }),
    export: (projectId: string, id: string, target: string, preview = false, config?: Record<string, unknown>) =>
      request(`/projects/${projectId}/executions/${id}/export/${target}`, {
        method: 'POST',
        body: JSON.stringify({ preview, config: config || {} })
      })
  },
  healing: {
    list: (projectId: string, automationKey?: string) =>
      request<HealingProposal[]>(
        `/projects/${projectId}/healing-proposals${automationKey ? `?automation_key=${encodeURIComponent(automationKey)}` : ''}`
      ),
    get: (projectId: string, proposalId: string) =>
      request<HealingProposal>(`/projects/${projectId}/healing-proposals/${proposalId}`),
    accept: (projectId: string, proposalId: string) =>
      request<HealingProposal>(`/projects/${projectId}/healing-proposals/${proposalId}/accept`, { method: 'POST' }),
    reject: (projectId: string, proposalId: string) =>
      request<HealingProposal>(`/projects/${projectId}/healing-proposals/${proposalId}/reject`, { method: 'POST' }),
    apply: (projectId: string, proposalId: string) =>
      request(`/projects/${projectId}/healing-proposals/${proposalId}/apply`, { method: 'POST' })
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

export interface ConnectorCredentialDescriptor {
  kind: string
  account: string
  label: string
  requiredFor?: string[]
}

export interface ConnectorCredentialInfo {
  id: string
  enabled: boolean
  config: Record<string, unknown>
  credentials: ConnectorCredentialDescriptor[]
  presenceSource: string
}

export interface ConnectorCredentialsResponse {
  service: string
  storage: string
  secretsReturned: false
  mask: string
  connectors: Record<string, ConnectorCredentialInfo>
}

export interface StructureValidationResponse {
  ok: boolean
  issues: string[]
  flowId?: string | null
}

export interface PromptComposerResponse {
  projectId: string
  batchPrompt: string
  selectedPresetId?: string | null
  caseOverrides: Record<string, string>
  overrides: Array<{
    caseId: string
    automationKey: string
    promptOverride: string
    updatedAt?: string | null
  }>
}

export interface PromptComposerUpdateRequest {
  batchPrompt: string
  selectedPresetId?: string | null
  caseOverrides: Record<string, string>
}

export interface PromptPreset {
  id: string
  projectId?: string | null
  category: string
  name: string
  guidance: string
  isBuiltin: boolean
  createdAt?: string | null
  updatedAt?: string | null
}

export interface PromptPresetsResponse {
  projectId: string
  presets: PromptPreset[]
}

export interface PromptPresetUpdateRequest {
  presets: Array<{
    id?: string | null
    category: string
    name: string
    guidance: string
  }>
}

export interface PromptPreviewRequest {
  caseId: string
  presetId?: string | null
  environment?: string
  startUrlOverride?: string | null
}

export interface PromptPreviewResponse {
  projectId: string
  caseId: string
  automationKey: string
  environment: string
  startUrl: string
  preset: PromptPreset | null
  parts: {
    basePrompt: string
    presetGuidance: string
    batchPrompt: string
    casePromptOverride: string
  }
  prompt: string
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

export interface ExecutionBootstrapSummary {
  ok?: boolean
  allOk?: boolean
  message?: string
  checks?: Record<string, boolean>
  pipError?: string
  playwrightError?: string
  playwrightBrowser?: { ok?: boolean; message?: string }
}

export interface ExecutionDetail {
  run: ExecutionRun
  results: ExecutionResult[]
  summary?: {
    bootstrap?: ExecutionBootstrapSummary
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

export type FailureDisposition = 'selector_changed' | 'raw_refresh_required' | 'feature_removed_retire_tc' | 'unknown'

export interface FailureTargetResolution {
  status: 'resolved' | 'missing' | 'ambiguous'
  reason: string
  execution_result_id?: string | null
  execution_run_id?: string | null
  project_id?: string | null
  automation_key?: string | null
  source_type?: string | null
  source_case_id?: string | null
  structured_step_id?: string | null
  page_object_method_id?: string | null
  test_case_ids: string[]
  generated_file_ids: string[]
  structured_flow_ids: string[]
  structured_step_ids: string[]
  page_object_method_ids: string[]
  mapping_ids: string[]
  raw_action_ids: string[]
  webwright_run_ids: string[]
  artifact_ids: string[]
}

export interface FailureDispositionDiagnosis {
  execution_result_id: string
  automation_key?: string | null
  disposition: FailureDisposition
  reason: string
  confidence: number
  evidence_artifact_ids: string[]
  selector_candidate_ids: string[]
  target: FailureTargetResolution
}

export interface ExecutionDiagnosis {
  project_id: string
  execution_id: string
  diagnoses: FailureDispositionDiagnosis[]
}

export interface HealingProposal {
  id: string
  project_id: string
  automation_key: string
  execution_result_id?: string | null
  page_object_method_id?: string | null
  structured_step_id?: string | null
  kind: string
  old_value?: string | null
  new_value: string
  confidence: number
  status: 'proposed' | 'accepted' | 'rejected' | 'applied' | 'superseded'
  evidence: unknown[]
  created_at?: string | null
  updated_at?: string | null
}

export interface HealingProposalActionResponse {
  status: string
  reason?: string
  proposal?: HealingProposal | null
  diagnosis?: FailureDispositionDiagnosis
  autoApply?: Record<string, unknown>
  apply?: unknown
}

export type LogStreamStatus = 'connecting' | 'open' | 'closed' | 'error'

export function connectLogStream(
  jobId: string,
  onMessage: (msg: string) => void,
  onStatus?: (status: LogStreamStatus) => void
): WebSocket {
  onStatus?.('connecting')
  const url = new URL(`${baseUrl.replace(/^http/, 'ws')}/ws/logs/${jobId}`)
  if (workerToken) url.searchParams.set('token', workerToken)
  const ws = new WebSocket(url.toString())
  ws.onopen = () => onStatus?.('open')
  ws.onmessage = (e) => onMessage(String(e.data))
  ws.onerror = () => onStatus?.('error')
  ws.onclose = () => onStatus?.('closed')
  return ws
}
