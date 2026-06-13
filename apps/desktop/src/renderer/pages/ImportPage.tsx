import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type NormalizedTestCase, type TestCase } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

type ImportSourceType = 'excel' | 'testrail-clone' | 'testrail' | 'google-sheets'

type ExcelColumnMapping = {
  case_id: string
  title: string
  precondition: string
  step: string
  expected: string
  priority: string
  automation_key: string
  start_url: string
}

type ExcelPreviewRow = {
  rowIndex: number
  caseId?: string | null
  title?: string | null
  automationKey?: string | null
  step?: string | null
  expected?: string | null
  startUrl?: string | null
}

type ExcelPreviewResponse = {
  headers: string[]
  preview: ExcelPreviewRow[]
  totalRows: number
}

type ImportSummary = {
  imported: number
  sampleTitles: string[]
}

type IntegrationSettings = {
  testrailClone?: { baseUrl?: string; enabled?: boolean }
  testrail?: { baseUrl?: string; enabled?: boolean }
  googleSheets?: { enabled?: boolean; spreadsheetId?: string }
}

const SOURCE_OPTIONS: { value: ImportSourceType; label: string }[] = [
  { value: 'excel', label: 'Excel' },
  { value: 'testrail-clone', label: 'testrail-clone' },
  { value: 'testrail', label: 'TestRail' },
  { value: 'google-sheets', label: 'Google Sheets' }
]

const DEFAULT_COLUMN_MAPPING: ExcelColumnMapping = {
  case_id: 'Case ID',
  title: 'Title',
  precondition: 'Precondition',
  step: 'Step',
  expected: 'Expected Result',
  priority: 'Priority',
  automation_key: 'Automation Key',
  start_url: 'Start URL'
}

const inputClass = 'w-full p-2 rounded bg-slate-950 border border-slate-700 text-sm'

export function ImportPage() {
  const project = useAppStore((s) => s.currentProject)
  const qc = useQueryClient()
  const [source, setSource] = useState<ImportSourceType>('excel')
  const [filePath, setFilePath] = useState('')
  const [sheetName, setSheetName] = useState('')
  const [columnMapping, setColumnMapping] = useState<ExcelColumnMapping>(DEFAULT_COLUMN_MAPPING)
  const [preview, setPreview] = useState<ExcelPreviewResponse | null>(null)
  const [importSummary, setImportSummary] = useState<ImportSummary | null>(null)
  const [cloneProjectId, setCloneProjectId] = useState('')
  const [cloneSuiteId, setCloneSuiteId] = useState('')
  const [clonePreview, setClonePreview] = useState<NormalizedTestCase[] | null>(null)
  const [testrailProjectId, setTestrailProjectId] = useState('')
  const [testrailSuiteId, setTestrailSuiteId] = useState('')
  const [testrailPreview, setTestrailPreview] = useState<NormalizedTestCase[] | null>(null)
  const [spreadsheetId, setSpreadsheetId] = useState('')
  const [sheetsPreview, setSheetsPreview] = useState<NormalizedTestCase[] | null>(null)

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.settings.get() as Promise<{ integrations?: IntegrationSettings }>
  })
  const integrations = settingsQuery.data?.integrations || {}
  const googleSheetsSpreadsheetId = spreadsheetId.trim() || integrations.googleSheets?.spreadsheetId || ''

  function buildExcelRequest() {
    return {
      file_path: filePath,
      sheet_name: sheetName.trim() || undefined,
      column_mapping: columnMapping
    }
  }

  function buildCloneRequest() {
    return {
      project_id: cloneProjectId.trim(),
      suite_id: cloneSuiteId.trim() || undefined
    }
  }

  function buildTestrailRequest() {
    return {
      project_id: Number(testrailProjectId),
      suite_id: testrailSuiteId.trim() ? Number(testrailSuiteId) : undefined
    }
  }

  async function runTestrailConnector(action: 'preview' | 'import'): Promise<NormalizedTestCase[]> {
    const body = buildTestrailRequest()
    if (window.electronAPI?.testrailImport) {
      const result = await window.electronAPI.testrailImport(project!.id, action, body)
      if (!result.ok) throw new Error(result.message)
      if (!Array.isArray(result.cases)) throw new Error('TestRail connector returned an unexpected response.')
      return result.cases as NormalizedTestCase[]
    }
    const fallbackBody = { ...body, mock: true }
    return action === 'preview'
      ? api.cases.previewTestrail(project!.id, fallbackBody)
      : api.cases.importTestrail(project!.id, fallbackBody)
  }

  function buildGoogleSheetsRequest() {
    return {
      spreadsheet_id: googleSheetsSpreadsheetId,
      sheet_name: sheetName.trim() || 'Cases',
      column_mapping: columnMapping
    }
  }

  async function runGoogleSheetsConnector(action: 'preview' | 'import'): Promise<NormalizedTestCase[]> {
    const body = buildGoogleSheetsRequest()
    if (window.electronAPI?.googleSheetsImport) {
      const result = await window.electronAPI.googleSheetsImport(project!.id, action, body)
      if (!result.ok) throw new Error(result.message)
      if (!Array.isArray(result.cases)) throw new Error('Google Sheets connector returned an unexpected response.')
      return result.cases as NormalizedTestCase[]
    }
    const fallbackBody = { ...body, mock: true }
    return action === 'preview'
      ? api.cases.previewGoogleSheets(project!.id, fallbackBody)
      : api.cases.importGoogleSheets(project!.id, fallbackBody)
  }

  async function pickFile() {
    const path = await window.electronAPI?.selectFile([{ name: 'Excel', extensions: ['xlsx', 'xls'] }])
    if (!path) return
    setFilePath(path)
    setPreview(null)
    setImportSummary(null)
  }

  function changeSource(next: ImportSourceType) {
    setSource(next)
    setPreview(null)
    setImportSummary(null)
    setClonePreview(null)
    setTestrailPreview(null)
    setSheetsPreview(null)
  }

  function updateColumnMapping(key: keyof ExcelColumnMapping, value: string) {
    setColumnMapping((current) => ({ ...current, [key]: value }))
    setPreview(null)
    setImportSummary(null)
    setSheetsPreview(null)
  }

  const previewMut = useMutation({
    mutationFn: () => api.cases.previewExcel(project!.id, buildExcelRequest()) as Promise<ExcelPreviewResponse>,
    onSuccess: (data) => {
      setPreview(data)
      setImportSummary(null)
    }
  })

  const importMut = useMutation({
    mutationFn: () => api.cases.importExcel(project!.id, buildExcelRequest()) as Promise<TestCase[]>,
    onSuccess: (cases) => {
      setImportSummary({
        imported: cases.length,
        sampleTitles: cases.slice(0, 5).map((item) => item.title)
      })
      setPreview(null)
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
    }
  })

  const clonePreviewMut = useMutation({
    mutationFn: () => api.cases.previewTestrailClone(project!.id, buildCloneRequest()),
    onSuccess: (data) => setClonePreview(data)
  })

  const cloneMut = useMutation({
    mutationFn: () => api.cases.importTestrailClone(project!.id, buildCloneRequest()),
    onSuccess: (cases) => {
      setImportSummary({
        imported: cases.length,
        sampleTitles: cases.slice(0, 5).map((item) => item.title)
      })
      setClonePreview(null)
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
    }
  })

  const testrailPreviewMut = useMutation({
    mutationFn: () => runTestrailConnector('preview'),
    onSuccess: (data) => setTestrailPreview(data)
  })

  const testrailImportMut = useMutation({
    mutationFn: () => runTestrailConnector('import'),
    onSuccess: (cases) => {
      setImportSummary({
        imported: cases.length,
        sampleTitles: cases.slice(0, 5).map((item) => item.title)
      })
      setTestrailPreview(null)
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
    }
  })

  const sheetsPreviewMut = useMutation({
    mutationFn: () => runGoogleSheetsConnector('preview'),
    onSuccess: (data) => setSheetsPreview(data)
  })

  const sheetsImportMut = useMutation({
    mutationFn: () => runGoogleSheetsConnector('import'),
    onSuccess: (cases) => {
      setImportSummary({
        imported: cases.length,
        sampleTitles: cases.slice(0, 5).map((item) => item.title)
      })
      setSheetsPreview(null)
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
    }
  })

  if (!project) return <p>Select a project on Dashboard first.</p>

  return (
    <div className="space-y-4 max-w-4xl">
      <h2 className="text-2xl font-bold">TC Import</h2>

      <section className="rounded border border-slate-800 bg-slate-900 p-4 space-y-3">
        <label className="block text-sm font-medium">Source type</label>
        <select
          className={inputClass}
          value={source}
          onChange={(e) => changeSource(e.target.value as ImportSourceType)}
        >
          {SOURCE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <p className="text-xs text-slate-500">
          {source === 'excel' && 'Import manual test cases from an Excel workbook.'}
          {source === 'testrail-clone' && 'Import cases from a local testrail-clone project.'}
          {source === 'testrail' && 'Connect to TestRail with project and suite identifiers.'}
          {source === 'google-sheets' && 'Import cases from a shared Google Sheet with column mapping.'}
        </p>
      </section>

      {source === 'excel' && (
        <section className="rounded border border-slate-800 bg-slate-900 p-4 space-y-4">
          <h3 className="text-sm font-medium">Excel import</h3>

          <div className="flex gap-2">
            <input
              className={`${inputClass} flex-1`}
              value={filePath}
              readOnly
              placeholder="Select an .xlsx or .xls file"
            />
            <button className="px-4 py-2 bg-slate-700 rounded shrink-0" type="button" onClick={pickFile}>
              Browse
            </button>
          </div>

          <label className="block text-xs text-slate-400">
            Sheet name
            <input
              className={`${inputClass} mt-1`}
              value={sheetName}
              onChange={(e) => {
                setSheetName(e.target.value)
                setPreview(null)
                setImportSummary(null)
              }}
              placeholder="Leave empty to use the active sheet"
            />
          </label>

          <ColumnMappingFields mapping={columnMapping} onChange={updateColumnMapping} />

          <div className="flex flex-wrap gap-2">
            <button
              className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
              disabled={!filePath || previewMut.isPending}
              type="button"
              onClick={() => previewMut.mutate()}
            >
              {previewMut.isPending ? 'Previewing...' : 'Preview'}
            </button>
            <button
              className="px-4 py-2 bg-green-600 rounded disabled:opacity-50"
              disabled={!filePath || importMut.isPending}
              type="button"
              onClick={() => importMut.mutate()}
            >
              {importMut.isPending ? 'Importing...' : 'Import'}
            </button>
          </div>

          {previewMut.isError && (
            <p className="text-sm text-red-400">Preview failed. Check the file path, sheet name, and column mapping.</p>
          )}
          {importMut.isError && (
            <p className="text-sm text-red-400">Import failed. Preview the file first if column headers changed.</p>
          )}

          {preview && (
            <div className="space-y-2">
              <p className="text-sm text-slate-400">
                Previewing {preview.preview.length} of {preview.totalRows} row(s)
              </p>
              <div className="overflow-auto rounded border border-slate-800">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-slate-950 text-left text-slate-400">
                      <th className="p-2">Row</th>
                      <th className="p-2">Case ID</th>
                      <th className="p-2">Title</th>
                      <th className="p-2">Automation Key</th>
                      <th className="p-2">Step</th>
                      <th className="p-2">Expected</th>
                      <th className="p-2">Start URL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview.map((row) => (
                      <tr key={row.rowIndex} className="border-t border-slate-800">
                        <td className="p-2">{row.rowIndex}</td>
                        <td className="p-2">{formatCell(row.caseId)}</td>
                        <td className="p-2">{formatCell(row.title)}</td>
                        <td className="p-2">{formatCell(row.automationKey)}</td>
                        <td className="p-2 max-w-xs truncate" title={formatCell(row.step)}>{formatCell(row.step)}</td>
                        <td className="p-2 max-w-xs truncate" title={formatCell(row.expected)}>{formatCell(row.expected)}</td>
                        <td className="p-2 max-w-xs truncate" title={formatCell(row.startUrl)}>{formatCell(row.startUrl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {importSummary && <ImportSummaryBanner summary={importSummary} />}
        </section>
      )}

      {source === 'testrail-clone' && (
        <section className="rounded border border-slate-800 bg-slate-900 p-4 space-y-4">
          <h3 className="text-sm font-medium">testrail-clone import</h3>
          <ConnectorIntegrationBanner
            enabled={integrations.testrailClone?.enabled === true}
            label="testrail-clone"
            baseUrl={integrations.testrailClone?.baseUrl}
          />
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs text-slate-400">
              Project ID
              <input
                className={`${inputClass} mt-1`}
                placeholder="testrail-clone projectId"
                value={cloneProjectId}
                onChange={(e) => {
                  setCloneProjectId(e.target.value)
                  setClonePreview(null)
                  setImportSummary(null)
                }}
              />
            </label>
            <label className="block text-xs text-slate-400">
              Suite ID (optional)
              <input
                className={`${inputClass} mt-1`}
                placeholder="Filter by suite"
                value={cloneSuiteId}
                onChange={(e) => {
                  setCloneSuiteId(e.target.value)
                  setClonePreview(null)
                }}
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
              disabled={!cloneProjectId || clonePreviewMut.isPending}
              type="button"
              onClick={() => clonePreviewMut.mutate()}
            >
              {clonePreviewMut.isPending ? 'Previewing...' : 'Preview'}
            </button>
            <button
              className="px-4 py-2 bg-green-600 rounded disabled:opacity-50"
              disabled={!cloneProjectId || cloneMut.isPending}
              type="button"
              onClick={() => cloneMut.mutate()}
            >
              {cloneMut.isPending ? 'Importing...' : 'Import from testrail-clone'}
            </button>
          </div>
          {clonePreviewMut.isError && (
            <p className="text-sm text-red-400">Preview failed. Check project ID, suite ID, and Settings → Integrations base URL.</p>
          )}
          {cloneMut.isError && (
            <p className="text-sm text-red-400">Import failed. Preview first to confirm connector access.</p>
          )}
          {clonePreview && <ConnectorCasePreviewTable cases={clonePreview} />}
          {importSummary && <ImportSummaryBanner summary={importSummary} />}
        </section>
      )}

      {source === 'testrail' && (
        <section className="rounded border border-slate-800 bg-slate-900 p-4 space-y-4">
          <h3 className="text-sm font-medium">TestRail import</h3>
          <ConnectorIntegrationBanner
            enabled={integrations.testrail?.enabled === true}
            label="TestRail"
            baseUrl={integrations.testrail?.baseUrl}
          />
          <p className="text-xs text-slate-500">
            API credentials are configured in Settings and used through the secure desktop credential path.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs text-slate-400">
              Project ID
              <input
                className={`${inputClass} mt-1`}
                placeholder="e.g. 12"
                value={testrailProjectId}
                onChange={(e) => {
                  setTestrailProjectId(e.target.value)
                  setTestrailPreview(null)
                }}
              />
            </label>
            <label className="block text-xs text-slate-400">
              Suite ID (optional)
              <input
                className={`${inputClass} mt-1`}
                placeholder="e.g. 3"
                value={testrailSuiteId}
                onChange={(e) => {
                  setTestrailSuiteId(e.target.value)
                  setTestrailPreview(null)
                }}
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
              disabled={!testrailProjectId || testrailPreviewMut.isPending}
              type="button"
              onClick={() => testrailPreviewMut.mutate()}
            >
              {testrailPreviewMut.isPending ? 'Previewing...' : 'Preview'}
            </button>
            <button
              className="px-4 py-2 bg-green-600 rounded disabled:opacity-50"
              disabled={!testrailProjectId || testrailImportMut.isPending}
              type="button"
              onClick={() => testrailImportMut.mutate()}
            >
              {testrailImportMut.isPending ? 'Importing...' : 'Import from TestRail'}
            </button>
          </div>
          {testrailPreviewMut.isError && (
            <p className="text-sm text-red-400">{mutationErrorText(testrailPreviewMut.error, 'Preview failed. Check project/suite IDs and TestRail integration settings.')}</p>
          )}
          {testrailImportMut.isError && (
            <p className="text-sm text-red-400">{mutationErrorText(testrailImportMut.error, 'Import failed. Preview first to confirm connector access.')}</p>
          )}
          {testrailPreview && (
            <ConnectorCasePreviewTable cases={testrailPreview} />
          )}
          {importSummary && <ImportSummaryBanner summary={importSummary} />}
        </section>
      )}

      {source === 'google-sheets' && (
        <section className="rounded border border-slate-800 bg-slate-900 p-4 space-y-4">
          <h3 className="text-sm font-medium">Google Sheets import</h3>
          <ConnectorIntegrationBanner
            enabled={integrations.googleSheets?.enabled === true}
            label="Google Sheets"
          />
          <p className="text-xs text-slate-500">
            OAuth or service account credentials are configured in Settings and used through the secure desktop credential path.
          </p>
          <label className="block text-xs text-slate-400">
            Spreadsheet ID
            <input
              className={`${inputClass} mt-1`}
              placeholder={integrations.googleSheets?.spreadsheetId || 'Spreadsheet ID from the sheet URL'}
              value={spreadsheetId}
              onChange={(e) => {
                setSpreadsheetId(e.target.value)
                setSheetsPreview(null)
              }}
            />
          </label>
          <label className="block text-xs text-slate-400">
            Sheet name
            <input
              className={`${inputClass} mt-1`}
              value={sheetName}
              onChange={(e) => {
                setSheetName(e.target.value)
                setSheetsPreview(null)
              }}
              placeholder="Cases"
            />
          </label>
          <ColumnMappingFields mapping={columnMapping} onChange={updateColumnMapping} />
          <div className="flex flex-wrap gap-2">
            <button
              className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
              disabled={!googleSheetsSpreadsheetId || sheetsPreviewMut.isPending}
              type="button"
              onClick={() => sheetsPreviewMut.mutate()}
            >
              {sheetsPreviewMut.isPending ? 'Previewing...' : 'Preview'}
            </button>
            <button
              className="px-4 py-2 bg-green-600 rounded disabled:opacity-50"
              disabled={!googleSheetsSpreadsheetId || sheetsImportMut.isPending}
              type="button"
              onClick={() => sheetsImportMut.mutate()}
            >
              {sheetsImportMut.isPending ? 'Importing...' : 'Import from Google Sheets'}
            </button>
          </div>
          {sheetsPreviewMut.isError && (
            <p className="text-sm text-red-400">{mutationErrorText(sheetsPreviewMut.error, 'Preview failed. Check spreadsheet ID, sheet name, and column mapping.')}</p>
          )}
          {sheetsImportMut.isError && (
            <p className="text-sm text-red-400">{mutationErrorText(sheetsImportMut.error, 'Import failed. Preview first to confirm connector access.')}</p>
          )}
          {sheetsPreview && (
            <ConnectorCasePreviewTable cases={sheetsPreview} />
          )}
          {importSummary && <ImportSummaryBanner summary={importSummary} />}
        </section>
      )}
    </div>
  )
}

function formatCell(value: unknown) {
  if (value == null || value === '') return '—'
  return String(value)
}

function mutationErrorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function ColumnMappingFields({
  mapping,
  onChange
}: {
  mapping: ExcelColumnMapping
  onChange: (key: keyof ExcelColumnMapping, value: string) => void
}) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-medium text-slate-400">Column mapping</h4>
      <div className="grid grid-cols-2 gap-3">
        {(Object.keys(DEFAULT_COLUMN_MAPPING) as Array<keyof ExcelColumnMapping>).map((key) => (
          <label key={key} className="block text-xs text-slate-400">
            {key.replace(/_/g, ' ')}
            <input
              className={`${inputClass} mt-1`}
              value={mapping[key]}
              onChange={(e) => onChange(key, e.target.value)}
            />
          </label>
        ))}
      </div>
    </div>
  )
}

function ConnectorIntegrationBanner({
  label,
  enabled,
  baseUrl
}: {
  label: string
  enabled: boolean
  baseUrl?: string
}) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-xs space-y-1">
      <div className="flex items-center gap-2">
        <span className="font-medium text-slate-300">{label}</span>
        <span className={`px-2 py-0.5 rounded ${enabled ? 'bg-green-900/40 text-green-300' : 'bg-slate-800 text-slate-400'}`}>
          {enabled ? 'Enabled in Settings' : 'Disabled in Settings'}
        </span>
      </div>
      {baseUrl ? (
        <p className="text-slate-500">Base URL: {baseUrl}</p>
      ) : (
        <p className="text-slate-500">Configure integration credentials in Settings → Integrations.</p>
      )}
    </div>
  )
}

function ConnectorCasePreviewTable({ cases }: { cases: NormalizedTestCase[] }) {
  return (
    <div className="space-y-2">
      <p className="text-sm text-slate-400">Previewing {cases.length} case(s)</p>
      <div className="overflow-auto rounded border border-slate-800">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-950 text-left text-slate-400">
              <th className="p-2">Source ID</th>
              <th className="p-2">Title</th>
              <th className="p-2">Automation Key</th>
              <th className="p-2">Steps</th>
              <th className="p-2">Expected</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((item) => (
              <tr key={`${item.source_id}-${item.automation_key}`} className="border-t border-slate-800">
                <td className="p-2">{formatCell(item.source_id)}</td>
                <td className="p-2">{formatCell(item.title)}</td>
                <td className="p-2">{formatCell(item.automation_key)}</td>
                <td className="p-2">{item.steps?.length ?? 0}</td>
                <td className="p-2 max-w-xs truncate" title={formatCell(item.expected_result)}>
                  {formatCell(item.expected_result ?? item.steps?.[0]?.expected)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ImportSummaryBanner({ summary }: { summary: ImportSummary }) {
  return (
    <div className="rounded border border-green-800 bg-green-950/20 p-3 text-sm">
      <div className="font-medium text-green-300">Import complete</div>
      <p className="mt-1 text-slate-300">Imported {summary.imported} test case(s). TC List will refresh on next view.</p>
      {summary.sampleTitles.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-slate-400">
          {summary.sampleTitles.map((title) => (
            <li key={title}>{title}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
