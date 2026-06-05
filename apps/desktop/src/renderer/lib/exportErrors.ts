import { getApiErrorMessage } from '@/lib/api'

export type ExportValidationIssue = {
  kind: string
  message: string
  automationKey?: string
  resultValue?: unknown
  expectedValue?: unknown
  error?: string
  file?: string
  sourceCaseId?: string
}

export type ExportErrorGuide = {
  category: string
  title: string
  summary: string
  actions: string[]
  issues: ExportValidationIssue[]
  preserveLocalResults: boolean
}

const issueTitles: Record<string, string> = {
  mapping_file_missing: 'Generated mapping file missing',
  mapping_load_failed: 'Generated mapping could not be loaded',
  mapping_cases_invalid: 'Generated mapping format invalid',
  missing_automation_key: 'Automation key missing',
  ambiguous_mapping: 'Duplicate mapping automation keys',
  ambiguous_execution_result: 'Duplicate execution result keys',
  missing_mapping: 'Mapping row missing for result',
  missing_execution_result: 'Execution result row missing',
  source_type_mismatch: 'Source type mismatch',
  source_case_id_mismatch: 'Source case ID mismatch'
}

const guides: Record<string, Omit<ExportErrorGuide, 'category' | 'issues'>> = {
  export_validation_failed: {
    title: 'Export validation failed',
    summary: 'Worker blocked export because result rows do not safely match generated mappings and execution results.',
    actions: [
      'Review the issue list below and fix mappings/cases.yaml or rerun execution for the affected automation keys.',
      'Run Preview again after mapping fixes. Local results.json is unchanged.'
    ],
    preserveLocalResults: true
  },
  results_missing: {
    title: 'Execution results missing',
    summary: 'Export could not find results.json for the selected execution.',
    actions: [
      'Select an execution that finished with a persisted result_path.',
      'Rerun the automation from the Runner panel, then retry export preview.'
    ],
    preserveLocalResults: true
  },
  testrail_token_error: {
    title: 'TestRail credentials rejected',
    summary: 'The configured TestRail token or account credentials were rejected.',
    actions: [
      'Open Settings and verify the TestRail URL, username, and API key.',
      'Retry export preview after saving valid credentials.'
    ],
    preserveLocalResults: true
  },
  testrail_clone_api_error: {
    title: 'testrail-clone API error',
    summary: 'The testrail-clone bulk results endpoint returned an error or was unreachable.',
    actions: [
      'Confirm testrail-clone base URL and service health in Settings.',
      'Inspect Worker logs, fix the API issue, then retry export.'
    ],
    preserveLocalResults: true
  },
  excel_file_locked: {
    title: 'Excel file locked',
    summary: 'Excel write-back could not save because the workbook is open or locked by another process.',
    actions: [
      'Close the workbook in Excel or any editor holding a lock on the source file.',
      'Retry export. Worker creates a timestamped backup before writing when the file is available.'
    ],
    preserveLocalResults: true
  },
  excel_source_missing: {
    title: 'Excel source file missing',
    summary: 'One or more Excel export targets referenced a workbook path that does not exist.',
    actions: [
      'Open mappings/cases.yaml and fix resultTargets.excel.file for the failed rows.',
      'Restore or relocate the source workbook, then retry export.'
    ],
    preserveLocalResults: true
  },
  google_sheets_permission_error: {
    title: 'Google Sheets permission error',
    summary: 'Google Sheets write-back was denied for the configured spreadsheet or service account.',
    actions: [
      'Verify spreadsheet sharing, service account access, and credentials in Settings.',
      'Retry export after granting the required editor permission.'
    ],
    preserveLocalResults: true
  },
  mapping_missing: {
    title: 'Export mapping incomplete',
    summary: 'Generated mappings are missing rows or target metadata required for export.',
    actions: [
      'Review mappings/cases.yaml and add the missing automationKey or resultTargets entries.',
      'Regenerate or edit mapping, then run Preview before export.'
    ],
    preserveLocalResults: true
  },
  unknown: {
    title: 'Export failed',
    summary: 'The Worker reported an export failure without a known recovery category.',
    actions: [
      'Read the raw export response below and Worker logs for the target-specific failure.',
      'Retry Preview first. Local results.json remains unchanged on validation failures.'
    ],
    preserveLocalResults: true
  }
}

function normalizeIssues(raw: unknown): ExportValidationIssue[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      kind: typeof item.kind === 'string' ? item.kind : 'unknown',
      message: typeof item.message === 'string' ? item.message : 'Export issue reported',
      automationKey: typeof item.automationKey === 'string' ? item.automationKey : undefined,
      resultValue: item.resultValue,
      expectedValue: item.expectedValue,
      error: typeof item.error === 'string' ? item.error : undefined,
      file: typeof item.file === 'string' ? item.file : undefined,
      sourceCaseId: typeof item.sourceCaseId === 'string' ? item.sourceCaseId : undefined
    }))
}

function issueLabel(issue: ExportValidationIssue) {
  const title = issueTitles[issue.kind] || issue.kind
  const key = issue.automationKey ? ` (${issue.automationKey})` : ''
  return `${title}${key}: ${issue.message}`
}

export function describeExportValidationIssues(
  issues: unknown,
  target: string
): ExportErrorGuide {
  const normalized = normalizeIssues(issues)
  const category = normalized.some((issue) => issue.kind.includes('mapping')) ? 'mapping_missing' : 'export_validation_failed'
  const guide = guides[category] || guides.export_validation_failed
  return {
    category,
    ...guide,
    summary: `${guide.summary} Target: ${target}.`,
    issues: normalized
  }
}

export function describeExportResultFailures(failed: unknown, target: string): ExportErrorGuide | null {
  const normalized = normalizeIssues(failed)
  if (!normalized.length) return null

  const hasMissingSource = normalized.some((issue) => issue.error === 'source file not found')
  const hasLocked = normalized.some((issue) => {
    const text = `${issue.error || ''} ${issue.message || ''}`.toLowerCase()
    return text.includes('locked') || text.includes('permission denied')
  })

  const category = hasLocked ? 'excel_file_locked' : hasMissingSource ? 'excel_source_missing' : 'unknown'
  const guide = guides[category] || guides.unknown
  return {
    category,
    ...guide,
    summary: `${guide.summary} Target: ${target}.`,
    issues: normalized
  }
}

export function describeExportApiError(error: unknown, target: string): ExportErrorGuide {
  const message = getApiErrorMessage(error, 'Export failed.')
  const normalized = message.toLowerCase()

  let category = 'unknown'
  if (normalized.includes('results.json not found')) category = 'results_missing'
  else if (normalized.includes('export validation failed')) category = 'export_validation_failed'
  else if (normalized.includes('missing_mapping') || normalized.includes('mapping_file_missing')) category = 'mapping_missing'
  else if (normalized.includes('401') || normalized.includes('unauthorized') || normalized.includes('token')) category = 'testrail_token_error'
  else if (normalized.includes('403') || normalized.includes('forbidden') || normalized.includes('permission')) {
    category = target === 'google-sheets' ? 'google_sheets_permission_error' : 'testrail_token_error'
  } else if (normalized.includes('locked') || normalized.includes('permission denied')) category = 'excel_file_locked'
  else if (target === 'testrail-clone' && (normalized.includes('connect') || normalized.includes('api') || normalized.includes('http'))) {
    category = 'testrail_clone_api_error'
  }

  const guide = guides[category] || guides.unknown
  const kinds = normalized.includes('export validation failed')
    ? message.replace(/^export validation failed:\s*/i, '').split(',').map((item) => item.trim()).filter(Boolean)
    : []

  const issues = kinds.map((kind) => ({
    kind,
    message: issueTitles[kind] || kind
  }))

  if (!issues.length && message) {
    issues.push({ kind: category, message })
  }

  return {
    category,
    ...guide,
    summary: `${guide.summary} Target: ${target}.`,
    issues
  }
}

export function buildExportOutcomeGuide(
  result: unknown,
  preview: boolean,
  target: string
): ExportErrorGuide | null {
  if (!result || typeof result !== 'object') return null
  const record = result as Record<string, unknown>

  if (!preview && Array.isArray(record.failed) && record.failed.length > 0) {
    return describeExportResultFailures(record.failed, target)
  }

  const validation = record.validation
  if (validation && typeof validation === 'object') {
    const issues = (validation as { ok?: boolean; issues?: unknown[] }).issues
    const ok = (validation as { ok?: boolean }).ok
    if (ok === false && Array.isArray(issues) && issues.length > 0) {
      return describeExportValidationIssues(issues, target)
    }
  }

  return null
}

export function formatExportIssue(issue: ExportValidationIssue) {
  return issueLabel(issue)
}
