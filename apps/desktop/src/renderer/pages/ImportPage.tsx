import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type TestCase } from '@/lib/api'
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

  function buildExcelRequest() {
    return {
      file_path: filePath,
      sheet_name: sheetName.trim() || undefined,
      column_mapping: columnMapping
    }
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
  }

  function updateColumnMapping(key: keyof ExcelColumnMapping, value: string) {
    setColumnMapping((current) => ({ ...current, [key]: value }))
    setPreview(null)
    setImportSummary(null)
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

  const cloneMut = useMutation({
    mutationFn: () => api.cases.importTestrailClone(project!.id, { project_id: cloneProjectId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cases', project?.id] })
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
          {source === 'testrail' && 'TestRail import is planned for a later phase.'}
          {source === 'google-sheets' && 'Google Sheets import is planned for a later phase.'}
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

          <div className="space-y-2">
            <h4 className="text-xs font-medium text-slate-400">Column mapping</h4>
            <div className="grid grid-cols-2 gap-3">
              {(Object.keys(DEFAULT_COLUMN_MAPPING) as Array<keyof ExcelColumnMapping>).map((key) => (
                <label key={key} className="block text-xs text-slate-400">
                  {key.replace(/_/g, ' ')}
                  <input
                    className={`${inputClass} mt-1`}
                    value={columnMapping[key]}
                    onChange={(e) => updateColumnMapping(key, e.target.value)}
                  />
                </label>
              ))}
            </div>
          </div>

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

          {importSummary && (
            <div className="rounded border border-green-800 bg-green-950/20 p-3 text-sm">
              <div className="font-medium text-green-300">Import complete</div>
              <p className="mt-1 text-slate-300">Imported {importSummary.imported} test case(s). TC List will refresh on next view.</p>
              {importSummary.sampleTitles.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-xs text-slate-400">
                  {importSummary.sampleTitles.map((title) => (
                    <li key={title}>{title}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      )}

      {source === 'testrail-clone' && (
        <section className="rounded border border-slate-800 bg-slate-900 p-4 space-y-2">
          <h3 className="text-sm font-medium">testrail-clone import</h3>
          <input
            className={inputClass}
            placeholder="testrail-clone projectId"
            value={cloneProjectId}
            onChange={(e) => setCloneProjectId(e.target.value)}
          />
          <button
            className="px-4 py-2 bg-green-600 rounded disabled:opacity-50"
            disabled={!cloneProjectId || cloneMut.isPending}
            type="button"
            onClick={() => cloneMut.mutate()}
          >
            {cloneMut.isPending ? 'Importing...' : 'Import from testrail-clone'}
          </button>
        </section>
      )}

      {source === 'testrail' && (
        <PlannedSourcePanel
          title="TestRail"
          description="Connect to TestRail with project, suite, and API credentials. Baseline connector UI ships in a later checklist batch."
        />
      )}

      {source === 'google-sheets' && (
        <PlannedSourcePanel
          title="Google Sheets"
          description="Import cases from a shared Google Sheet after OAuth or service account setup. Baseline connector UI ships in a later checklist batch."
        />
      )}
    </div>
  )
}

function formatCell(value: unknown) {
  if (value == null || value === '') return '—'
  return String(value)
}

function PlannedSourcePanel({ title, description }: { title: string; description: string }) {
  return (
    <section className="rounded border border-dashed border-slate-700 bg-slate-900/50 p-4 space-y-2">
      <h3 className="text-sm font-medium text-slate-300">{title}</h3>
      <p className="text-sm text-slate-400">{description}</p>
      <p className="text-xs text-slate-500">This source type is listed for workflow planning; import actions are disabled until the connector baseline lands.</p>
    </section>
  )
}
