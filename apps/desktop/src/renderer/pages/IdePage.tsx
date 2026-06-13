import { useEffect, useRef, useState, type ReactNode } from 'react'
import Editor from '@monaco-editor/react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import {
  api,
  connectLogStream,
  getApiErrorMessage,
  type ExecutionResult,
  type ExecutionRun,
  type FailureDispositionDiagnosis,
  type HealingProposal
} from '@/lib/api'
import {
  MaintenanceImpactReview,
  maintenanceSummaryFromRefreshPreview,
  maintenanceSummaryFromRetirePreview,
  type MaintenanceImpactSummary
} from '@/components/MaintenanceImpactReview'
import {
  buildGenerationConflictSummary,
  generationConflictGuidance,
  maintenanceSummaryFromGenerationPreview
} from '@/lib/generationConflict'
import { describeExecutionError } from '@/lib/executionErrors'
import { ExecutionRunErrorPanel } from '@/components/ExecutionRunErrorPanel'
import {
  buildExportOutcomeGuide,
  describeExportApiError,
  type ExportErrorGuide
} from '@/lib/exportErrors'
import { ExportErrorPanel } from '@/components/ExportErrorPanel'
import { useAppStore } from '@/store/appStore'

type GeneratedFileItem = {
  path: string
  type: string
}

type FileTreeNode = {
  name: string
  path: string
  type: 'directory' | 'file'
  children: FileTreeNode[]
}

type IdeRunTarget = 'linked' | 'all' | 'selected'
type IdePanel = 'runner' | 'results' | 'diagnosis' | 'export'

type ExecutionSummaryCase = {
  automationKey?: string
  automation_key?: string
  artifacts?: {
    screenshot?: string | null
    trace?: string | null
  }
  error?: string | null
  status: string
  title?: string | null
}

type DiagnosisRow = {
  caseId: string
  diagnosis: FailureDispositionDiagnosis
  automationKey: string
  error: string
  executionResultId: string
  sourceCaseId: string
  sourceType: string
  screenshotPath: string
  status: string
  title: string
  tracePath: string
}

type HealingProposalStatus = HealingProposal['status'] | 'not_applicable'

export function IdePage() {
  const navigate = useNavigate()
  const project = useAppStore((s) => s.currentProject)
  const selectedCase = useAppStore((s) => s.selectedCase)
  const appendLog = useAppStore((s) => s.appendLog)
  const clearLogs = useAppStore((s) => s.clearLogs)
  const logs = useAppStore((s) => s.logs)
  const [selectedPath, setSelectedPath] = useState('')
  const [content, setContent] = useState('')
  const [savedContent, setSavedContent] = useState('')
  const [loadingPath, setLoadingPath] = useState('')
  const [editorStatus, setEditorStatus] = useState('Select a generated file.')
  const [runStatus, setRunStatus] = useState('No IDE run started.')
  const [runtimeActionStatus, setRuntimeActionStatus] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [activePanel, setActivePanel] = useState<IdePanel>('runner')
  const [runnerEnv, setRunnerEnv] = useState(project?.default_env || 'stg')
  const [runnerBrowser, setRunnerBrowser] = useState('chromium')
  const [runnerHeaded, setRunnerHeaded] = useState(false)
  const [runnerTarget, setRunnerTarget] = useState<IdeRunTarget>('all')
  const [runnerAutomationKey, setRunnerAutomationKey] = useState('')
  const [runnerCaseIds, setRunnerCaseIds] = useState('')
  const [runnerResultTarget, setRunnerResultTarget] = useState('local')
  const [selectedExecutionId, setSelectedExecutionId] = useState('')
  const [exportTarget, setExportTarget] = useState('testrail-clone')
  const [exportPreview, setExportPreview] = useState<unknown>(null)
  const [exportErrorGuide, setExportErrorGuide] = useState<ExportErrorGuide | null>(null)
  const [generationConflict, setGenerationConflict] = useState<MaintenanceImpactSummary | null>(null)
  const [generationReview, setGenerationReview] = useState<{
    pending: { caseIds: string[] }
    summary: MaintenanceImpactSummary
  } | null>(null)
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set())
  const termRef = useRef<HTMLDivElement>(null)
  const termInstanceRef = useRef<Terminal | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const renderedLogCountRef = useRef(0)
  const qc = useQueryClient()

  const { data: files = [] } = useQuery({
    queryKey: ['generated-files', project?.id],
    queryFn: () => api.generation.files(project!.id),
    enabled: !!project
  })

  useEffect(() => {
    const dirs = (files as GeneratedFileItem[]).filter((f) => f.type === 'directory').map((f) => f.path)
    setExpandedDirs((current) => new Set([...current, ...dirs]))
  }, [files])

  const { data: searchResults = [] } = useQuery({
    queryKey: ['search', project?.id, searchQ],
    queryFn: () => api.generation.search(project!.id, searchQ),
    enabled: !!project && searchQ.length > 1
  })

  const { data: executions = [] } = useQuery({
    queryKey: ['executions', project?.id],
    queryFn: () => api.executions.list(project!.id),
    enabled: !!project,
    refetchInterval: 5000
  })

  const latestExecution = latestExecutionRun(executions)
  const selectedExecution = selectedExecutionId
    ? executions.find((execution) => execution.id === selectedExecutionId) || latestExecution
    : latestExecution
  const { data: executionDetail } = useQuery({
    queryKey: ['execution-detail', project?.id, selectedExecution?.id],
    queryFn: () => api.executions.get(project!.id, selectedExecution!.id),
    enabled: !!project && !!selectedExecution?.id,
    refetchInterval: 5000
  })

  const loadFile = async (path: string) => {
    if (!project) return
    setLoadingPath(path)
    setEditorStatus(`Loading ${path}...`)
    const res = await api.generation.content(project.id, path)
    setSelectedPath(path)
    setContent(res.content)
    setSavedContent(res.content)
    setEditorStatus(`Loaded ${path}`)
    setLoadingPath('')
  }

  const saveMut = useMutation({
    mutationFn: () => api.generation.save(project!.id, selectedPath, content),
    onSuccess: () => {
      setSavedContent(content)
      setEditorStatus(`Saved ${selectedPath}`)
      qc.invalidateQueries({ queryKey: ['generated-files', project?.id] })
    },
    onError: (error) => {
      setEditorStatus(error instanceof Error ? error.message : 'Save failed.')
    }
  })

  function showGenerationConflict(error: unknown, actionLabel: string) {
    const summary = buildGenerationConflictSummary(error, actionLabel)
    if (!summary) return false
    setGenerationConflict(summary)
    setGenerationReview(null)
    return true
  }

  const generateMut = useMutation({
    mutationFn: () => api.generation.generate(project!.id),
    onMutate: () => {
      setGenerationConflict(null)
      setGenerationReview(null)
    },
    onSuccess: () => {
      setGenerationConflict(null)
      setGenerationReview(null)
      setEditorStatus('Project generated.')
      qc.invalidateQueries({ queryKey: ['generated-files', project?.id] })
    },
    onError: (error) => {
      if (!showGenerationConflict(error, 'Full project generation')) {
        setEditorStatus(getApiErrorMessage(error, 'Generation failed.'))
      }
    }
  })

  const previewGenerateMut = useMutation({
    mutationFn: (caseIds: string[]) => api.generation.previewSelected(project!.id, { caseIds }),
    onSuccess: (res, caseIds) => {
      const summary = maintenanceSummaryFromGenerationPreview(
        res as Record<string, unknown>,
        caseIds.length === 1 ? 'Selected TC regeneration' : 'Selected regeneration'
      )
      summary.guidance = generationConflictGuidance(summary)
      setGenerationReview({ pending: { caseIds }, summary })
      setGenerationConflict(null)
      setEditorStatus('Review regeneration impact before applying.')
    },
    onError: (error) => {
      if (!showGenerationConflict(error, 'Selected regeneration preview')) {
        setEditorStatus(getApiErrorMessage(error, 'Regeneration preview failed.'))
      }
    }
  })

  const generateSelectedMut = useMutation({
    mutationFn: (caseIds: string[]) => api.generation.generateSelected(project!.id, { caseIds }),
    onMutate: () => setGenerationConflict(null),
    onSuccess: () => {
      setGenerationConflict(null)
      setGenerationReview(null)
      setEditorStatus('Selected regeneration completed.')
      qc.invalidateQueries({ queryKey: ['generated-files', project?.id] })
    },
    onError: (error) => {
      if (!showGenerationConflict(error, 'Selected regeneration')) {
        setEditorStatus(getApiErrorMessage(error, 'Selected regeneration failed.'))
      }
    }
  })

  const runMut = useMutation({
    mutationFn: async (options: {
      automationKey?: string
      browser?: string
      caseIds?: string[]
      env?: string
      headed?: boolean
      resultTarget?: string
      target: IdeRunTarget
    }) => {
      if (!project) throw new Error('Select a project first.')
      const linkedCase = selectedCase?.project_id === project.id ? selectedCase : null
      const automationKey = options.automationKey || linkedCase?.automation_key || ''
      if (options.target === 'linked' && !automationKey) throw new Error('Select a linked TC first.')
      if (options.target === 'selected' && !options.caseIds?.length) throw new Error('Enter at least one case ID.')

      const body = options.target === 'linked'
        ? {
            env: options.env || 'stg',
            browser: options.browser || 'chromium',
            headed: options.headed || false,
            target_type: 'case',
            automation_key: automationKey,
            result_target: options.resultTarget || 'local'
          }
        : options.target === 'selected'
          ? {
              env: options.env || 'stg',
              browser: options.browser || 'chromium',
              headed: options.headed || false,
              target_type: 'selected',
              case_ids: options.caseIds || [],
              result_target: options.resultTarget || 'local'
            }
          : {
              env: options.env || 'stg',
              browser: options.browser || 'chromium',
              headed: options.headed || false,
              target_type: 'all',
              result_target: options.resultTarget || 'local'
            }
      setRunStatus(options.target === 'linked'
        ? `Queueing ${automationKey}...`
        : options.target === 'selected'
          ? `Queueing ${options.caseIds?.length || 0} selected case(s)...`
          : 'Queueing all generated TCs...')
      const res = await api.executions.run(project.id, body)
      connectLogStream(res.jobId, appendLog)
      return { automationKey, jobId: res.jobId, target: options.target }
    },
    onSuccess: ({ automationKey, jobId, target }) => {
      setRunStatus(target === 'linked'
        ? `Queued ${automationKey} (${jobId})`
        : target === 'selected'
          ? `Queued selected cases (${jobId})`
          : `Queued all generated TCs (${jobId})`)
      qc.invalidateQueries({ queryKey: ['executions', project?.id] })
    },
    onError: (error) => {
      setRunStatus(error instanceof Error ? error.message : 'Run failed.')
    }
  })

  const installRuntimeMut = useMutation({
    mutationFn: async () => {
      if (!project?.generated_project_path) throw new Error('Generate a project first.')
      return api.installDeps(project.id, project.generated_project_path)
    },
    onMutate: () => setRuntimeActionStatus('Installing Python deps and browser...'),
    onSuccess: (res) => {
      setRuntimeActionStatus(
        res.ok || res.allOk
          ? 'Runtime ready.'
          : `Install failed: ${res.message || res.pipError || 'unknown'}`
      )
    },
    onError: (error) => {
      setRuntimeActionStatus(error instanceof Error ? error.message : 'Install failed.')
    }
  })

  const healthCheckMut = useMutation({
    mutationFn: async () => {
      if (!project?.generated_project_path) return api.health()
      return api.projectHealth(project.id, project.generated_project_path)
    },
    onMutate: () => setRuntimeActionStatus('Running health check...'),
    onSuccess: (res) => {
      setRuntimeActionStatus(
        res.allOk || res.ok
          ? 'Health check passed.'
          : `Health check failed: ${res.message || 'see runtime checks'}`
      )
    },
    onError: (error) => {
      setRuntimeActionStatus(error instanceof Error ? error.message : 'Health check failed.')
    }
  })

  const rerunFailedMut = useMutation({
    mutationFn: async () => {
      if (!project || !selectedExecution?.id) throw new Error('Select an execution first.')
      clearLogs()
      const res = await api.executions.rerunFailed(project.id, selectedExecution.id)
      connectLogStream(res.jobId, appendLog)
      return res
    },
    onSuccess: (res) => {
      setRunStatus(`Rerun-failed queued (${res.jobId})`)
      qc.invalidateQueries({ queryKey: ['executions', project?.id] })
    },
    onError: (error) => {
      setRunStatus(error instanceof Error ? error.message : 'Rerun-failed failed.')
    }
  })

  async function runExport(preview: boolean) {
    if (!project || !selectedExecution?.id) throw new Error('Select an execution first.')
    if (exportTarget === 'testrail' && window.electronAPI?.testrailExport) {
      const result = await window.electronAPI.testrailExport(project.id, selectedExecution.id, preview)
      if (!result.ok) throw new Error(result.message)
      return result.result
    }
    if (exportTarget === 'google-sheets' && window.electronAPI?.googleSheetsExport) {
      const result = await window.electronAPI.googleSheetsExport(project.id, selectedExecution.id, preview)
      if (!result.ok) throw new Error(result.message)
      return result.result
    }
    const config = ['testrail', 'google-sheets'].includes(exportTarget) && !preview ? { mock: true } : undefined
    return api.executions.export(project.id, selectedExecution.id, exportTarget, preview, config)
  }

  const exportMut = useMutation({
    mutationFn: (preview: boolean) => runExport(preview),
    onSuccess: (result, preview) => {
      setExportPreview(result)
      setExportErrorGuide(buildExportOutcomeGuide(result, preview, exportTarget))
    },
    onError: (error) => {
      setExportPreview({ error: getApiErrorMessage(error, 'Export failed.') })
      setExportErrorGuide(describeExportApiError(error, exportTarget))
    }
  })

  useEffect(() => {
    setExportPreview(null)
    setExportErrorGuide(null)
  }, [selectedExecution?.id, exportTarget])

  useEffect(() => {
    if (!termRef.current) return
    const term = new Terminal({ theme: { background: '#0f172a' }, convertEol: true })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(termRef.current)
    fit.fit()
    term.writeln('Project IDE terminal ready.')
    termInstanceRef.current = term
    fitAddonRef.current = fit
    return () => {
      term.dispose()
      termInstanceRef.current = null
      fitAddonRef.current = null
      renderedLogCountRef.current = 0
    }
  }, [])

  useEffect(() => {
    const term = termInstanceRef.current
    if (!term) return
    if (logs.length < renderedLogCountRef.current) {
      term.clear()
      renderedLogCountRef.current = 0
    }
    const nextLogs = logs.slice(renderedLogCountRef.current)
    nextLogs.forEach((line) => term.writeln(line))
    renderedLogCountRef.current = logs.length
  }, [logs])

  if (!project) return <p>Select a project first.</p>

  const selectedCaseInProject = selectedCase?.project_id === project.id ? selectedCase : null
  const fileTree = buildFileTree(files as GeneratedFileItem[])
  const isDirty = selectedPath ? content !== savedContent : false
  const editorLanguage = languageForPath(selectedPath)
  const latestResult = selectedCaseInProject
    ? latestResultForCase(executionDetail?.results, selectedCaseInProject.automation_key)
    : executionDetail?.results?.[0]
  const summaryResult = selectedCaseInProject
    ? latestSummaryCaseForCase(executionDetail?.summary?.cases, selectedCaseInProject.automation_key)
    : executionDetail?.summary?.cases?.[0]
  const screenshotPath = latestResult?.screenshot_path || summaryResult?.artifacts?.screenshot || ''
  const tracePath = latestResult?.trace_path || summaryResult?.artifacts?.trace || ''
  const resolvedScreenshotPath = resolveArtifactPath(executionDetail?.run.result_path, screenshotPath)
  const resolvedTracePath = resolveArtifactPath(executionDetail?.run.result_path, tracePath)
  const failedResultError = executionDetail?.results?.find((result) => result.status === 'failed')?.error ||
    executionDetail?.summary?.cases?.find((item) => item.status === 'failed')?.error ||
    executionDetail?.summary?.bootstrap?.message
  const executionErrorGuide = describeExecutionError({
    bootstrap: executionDetail?.summary?.bootstrap,
    runStatus: selectedExecution?.status,
    primaryError: failedResultError,
    failedCount: executionDetail?.summary?.summary?.failed ??
      executionDetail?.results?.filter((result) => result.status === 'failed').length
  })

  function retryRunner() {
    runMut.mutate({
      automationKey: runnerAutomationKey || selectedCaseInProject?.automation_key,
      browser: runnerBrowser,
      caseIds: parseCaseIds(runnerCaseIds),
      env: runnerEnv,
      headed: runnerHeaded,
      resultTarget: runnerResultTarget,
      target: runnerTarget
    })
  }

  return (
    <div className="space-y-3 h-[calc(100vh-6rem)] flex flex-col">
      <div className="flex gap-2">
        <h2 className="text-2xl font-bold flex-1">Project IDE</h2>
        {selectedCaseInProject && (
          <button className="px-3 py-1 bg-slate-700 rounded" onClick={() => navigate('/webwright')}>
            Rerun Raw
          </button>
        )}
        <button
          className="px-3 py-1 bg-purple-600 rounded disabled:opacity-50"
          disabled={generateMut.isPending || previewGenerateMut.isPending || generateSelectedMut.isPending}
          onClick={() => generateMut.mutate()}
        >
          {generateMut.isPending ? 'Generating...' : 'Generate Project'}
        </button>
        {selectedCaseInProject && (
          <>
            <button
              className="px-3 py-1 bg-slate-700 rounded disabled:opacity-50"
              disabled={previewGenerateMut.isPending || generateMut.isPending || generateSelectedMut.isPending}
              onClick={() => previewGenerateMut.mutate([selectedCaseInProject.id])}
            >
              {previewGenerateMut.isPending ? 'Previewing...' : 'Preview Regenerate'}
            </button>
            <button
              className="px-3 py-1 bg-indigo-700 rounded disabled:opacity-50"
              disabled={generateSelectedMut.isPending || generateMut.isPending || previewGenerateMut.isPending}
              onClick={() => generateSelectedMut.mutate([selectedCaseInProject.id])}
            >
              {generateSelectedMut.isPending ? 'Regenerating...' : 'Regenerate Linked TC'}
            </button>
          </>
        )}
        <button
          className="px-3 py-1 bg-green-600 rounded disabled:opacity-50"
          disabled={!selectedPath || !isDirty || saveMut.isPending}
          onClick={() => saveMut.mutate()}
        >
          {saveMut.isPending ? 'Saving...' : 'Save'}
        </button>
        <button
          className="px-3 py-1 bg-blue-600 rounded disabled:opacity-50"
          disabled={!selectedCaseInProject || runMut.isPending}
          onClick={() => runMut.mutate({ target: 'linked' })}
        >
          {runMut.isPending ? 'Running...' : 'Run Linked TC'}
        </button>
        <button
          className="px-3 py-1 bg-slate-700 rounded disabled:opacity-50"
          disabled={runMut.isPending}
          onClick={() => runMut.mutate({ target: 'all' })}
        >
          Run All
        </button>
      </div>

      {generationConflict && (
        <MaintenanceImpactReview
          summary={generationConflict}
          pending={false}
          onDismiss={() => setGenerationConflict(null)}
          onApply={() => setGenerationConflict(null)}
        />
      )}
      {generationReview && (
        <MaintenanceImpactReview
          summary={generationReview.summary}
          pending={generateMut.isPending || generateSelectedMut.isPending}
          onDismiss={() => setGenerationReview(null)}
          onApply={() => generateSelectedMut.mutate(generationReview.pending.caseIds)}
        />
      )}

      <input className="p-2 rounded bg-slate-800" placeholder="Search automationKey / selector" value={searchQ} onChange={(e) => setSearchQ(e.target.value)} />

      <div className="flex flex-1 gap-3 min-h-0">
        <div className="w-64 bg-slate-900 rounded border border-slate-800 overflow-hidden text-sm">
          <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
            <h3 className="text-sm font-semibold">Generated Files</h3>
            <span className="text-xs text-slate-500">{files.length}</span>
          </div>
          <div className="h-full overflow-auto p-2">
            <FileTree
              expandedDirs={expandedDirs}
              nodes={fileTree}
              onLoadFile={loadFile}
              onToggleDir={(path) => {
                setExpandedDirs((current) => {
                  const next = new Set(current)
                  if (next.has(path)) next.delete(path)
                  else next.add(path)
                  return next
                })
              }}
              selectedPath={selectedPath}
            />
            {!fileTree.length && (
              <div className="p-3 text-xs text-slate-500">No generated files yet.</div>
            )}
          </div>
        </div>
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex items-center justify-between rounded-t border border-b-0 border-slate-700 bg-slate-900 px-3 py-2 text-xs">
            <div className="min-w-0 truncate text-slate-300">{selectedPath || 'No file selected'}</div>
            <div className="flex shrink-0 items-center gap-2 text-slate-500">
              <span>{editorLanguage}</span>
              <span className={isDirty ? 'text-yellow-300' : 'text-green-400'}>{isDirty ? 'Unsaved' : selectedPath ? 'Saved' : 'Idle'}</span>
            </div>
          </div>
          <div className="flex-1 border border-slate-700 rounded-b overflow-hidden">
            {loadingPath ? (
              <div className="p-4 text-slate-400">Loading {loadingPath}...</div>
            ) : selectedPath ? (
              <Editor
                height="100%"
                language={editorLanguage}
                options={{ minimap: { enabled: false }, scrollBeyondLastLine: false, wordWrap: 'on' }}
                path={selectedPath}
                theme="vs-dark"
                value={content}
                onChange={(v) => {
                  setContent(v || '')
                  setEditorStatus(`Editing ${selectedPath}`)
                }}
              />
            ) : (
              <div className="p-4 text-slate-400">Select a file</div>
            )}
          </div>
          <div className="mt-1 text-xs text-slate-500">{editorStatus}</div>
          <div className="mt-2 overflow-hidden rounded border border-slate-700">
            <div className="flex items-center justify-between border-b border-slate-700 bg-slate-900 px-3 py-1 text-xs">
              <span className="text-slate-300">Terminal</span>
              <span className="text-slate-500">{logs.length} log(s)</span>
            </div>
            <div ref={termRef} className="h-32" />
          </div>
          <div className="mt-2 overflow-hidden rounded border border-slate-700 bg-slate-950">
            <div className="flex items-center justify-between border-b border-slate-700 bg-slate-900 px-3 py-2">
              <div className="flex gap-2">
                <PanelTab active={activePanel === 'runner'} label="Runner" onClick={() => setActivePanel('runner')} />
                <PanelTab active={activePanel === 'results'} label="Results" onClick={() => setActivePanel('results')} />
                <PanelTab active={activePanel === 'diagnosis'} label="Diagnosis" onClick={() => setActivePanel('diagnosis')} />
                <PanelTab active={activePanel === 'export'} label="Export" onClick={() => setActivePanel('export')} />
              </div>
              <span className="text-xs text-slate-500">Automation IDE panels</span>
            </div>
            <div className="max-h-72 overflow-auto p-3 text-sm">
              {activePanel === 'runner' && (
                <div className="space-y-3">
                  <div className="grid grid-cols-4 gap-3">
                    <label className="text-xs text-slate-400">
                      Environment
                      <select className="mt-1 w-full rounded bg-slate-800 p-2 text-slate-200" value={runnerEnv} onChange={(e) => setRunnerEnv(e.target.value)}>
                        <option>local</option>
                        <option>stg</option>
                        <option>prod</option>
                      </select>
                    </label>
                    <label className="text-xs text-slate-400">
                      Browser
                      <select className="mt-1 w-full rounded bg-slate-800 p-2 text-slate-200" value={runnerBrowser} onChange={(e) => setRunnerBrowser(e.target.value)}>
                        <option>chromium</option>
                        <option>firefox</option>
                        <option>webkit</option>
                      </select>
                    </label>
                    <label className="text-xs text-slate-400">
                      Target
                      <select className="mt-1 w-full rounded bg-slate-800 p-2 text-slate-200" value={runnerTarget} onChange={(e) => setRunnerTarget(e.target.value as IdeRunTarget)}>
                        <option value="all">All</option>
                        <option value="linked">Linked TC</option>
                        <option value="selected">Case IDs</option>
                      </select>
                    </label>
                    <label className="text-xs text-slate-400">
                      Result Target
                      <select className="mt-1 w-full rounded bg-slate-800 p-2 text-slate-200" value={runnerResultTarget} onChange={(e) => setRunnerResultTarget(e.target.value)}>
                        <option value="local">local only</option>
                        <option value="testrail-clone">testrail-clone</option>
                        <option value="testrail">TestRail</option>
                        <option value="excel">Excel</option>
                        <option value="google-sheets">Google Sheets</option>
                      </select>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-300">
                      <input checked={runnerHeaded} type="checkbox" onChange={(e) => setRunnerHeaded(e.target.checked)} />
                      Headed
                    </label>
                  </div>
                  {runnerTarget === 'linked' && (
                    <input
                      className="w-full rounded bg-slate-800 p-2 text-sm"
                      placeholder={selectedCaseInProject?.automation_key || 'automationKey'}
                      value={runnerAutomationKey}
                      onChange={(e) => setRunnerAutomationKey(e.target.value)}
                    />
                  )}
                  {runnerTarget === 'selected' && (
                    <textarea
                      className="w-full rounded bg-slate-800 p-2 text-sm"
                      placeholder="case IDs or automation keys, comma/newline separated"
                      rows={3}
                      value={runnerCaseIds}
                      onChange={(e) => setRunnerCaseIds(e.target.value)}
                    />
                  )}
                  <div className="text-xs text-slate-500">{runStatus}</div>
                  {runtimeActionStatus && <div className="text-xs text-slate-400">{runtimeActionStatus}</div>}
                  {executionErrorGuide && (
                    <ExecutionRunErrorPanel
                      guide={executionErrorGuide}
                      healthPending={healthCheckMut.isPending}
                      installPending={installRuntimeMut.isPending}
                      onHealthCheck={() => healthCheckMut.mutate()}
                      onInstallDeps={() => installRuntimeMut.mutate()}
                      onOpenDiagnosis={() => setActivePanel('diagnosis')}
                      onRetry={retryRunner}
                      onRerunFailed={() => rerunFailedMut.mutate()}
                      rerunPending={rerunFailedMut.isPending}
                      resultPath={executionDetail?.run.result_path}
                      retryPending={runMut.isPending}
                    />
                  )}
                  <div className="flex flex-wrap gap-2">
                    <button
                      className="rounded bg-slate-700 px-3 py-2 text-sm disabled:opacity-50"
                      disabled={!project.generated_project_path || installRuntimeMut.isPending}
                      type="button"
                      onClick={() => installRuntimeMut.mutate()}
                    >
                      {installRuntimeMut.isPending ? 'Installing...' : 'Install Dependencies'}
                    </button>
                    <button
                      className="rounded bg-slate-700 px-3 py-2 text-sm disabled:opacity-50"
                      disabled={healthCheckMut.isPending}
                      type="button"
                      onClick={() => healthCheckMut.mutate()}
                    >
                      {healthCheckMut.isPending ? 'Checking...' : 'Health Check'}
                    </button>
                    <button
                      className="rounded bg-green-600 px-3 py-2 text-sm disabled:opacity-50"
                      disabled={
                        runMut.isPending ||
                        (runnerTarget === 'linked' && !runnerAutomationKey && !selectedCaseInProject) ||
                        (runnerTarget === 'selected' && parseCaseIds(runnerCaseIds).length === 0)
                      }
                      type="button"
                      onClick={retryRunner}
                    >
                      {runMut.isPending ? 'Running...' : 'Run'}
                    </button>
                  </div>
                </div>
              )}

              {activePanel === 'results' && (
                <div className="space-y-3">
                  <ExecutionSelect executions={executions} selectedId={selectedExecution?.id || ''} onChange={setSelectedExecutionId} />
                  {executionErrorGuide && (
                    <ExecutionRunErrorPanel
                      compact
                      guide={executionErrorGuide}
                      healthPending={healthCheckMut.isPending}
                      installPending={installRuntimeMut.isPending}
                      onHealthCheck={() => healthCheckMut.mutate()}
                      onInstallDeps={() => installRuntimeMut.mutate()}
                      onOpenDiagnosis={() => setActivePanel('diagnosis')}
                      onRetry={retryRunner}
                      onRerunFailed={() => rerunFailedMut.mutate()}
                      rerunPending={rerunFailedMut.isPending}
                      resultPath={executionDetail?.run.result_path}
                      retryPending={runMut.isPending}
                    />
                  )}
                  {executionDetail?.summary?.summary && <SummaryGrid summary={executionDetail.summary.summary} />}
                  <ResultTable rows={executionDetail?.summary?.cases || executionDetail?.results || []} />
                </div>
              )}

              {activePanel === 'export' && (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    <ExecutionSelect executions={executions} selectedId={selectedExecution?.id || ''} onChange={setSelectedExecutionId} />
                    <select className="rounded bg-slate-800 p-2 text-sm text-slate-200" value={exportTarget} onChange={(e) => setExportTarget(e.target.value)}>
                      <option value="testrail-clone">testrail-clone</option>
                      <option value="testrail">TestRail</option>
                      <option value="excel">Excel</option>
                      <option value="google-sheets">Google Sheets</option>
                    </select>
                    <button className="rounded bg-slate-700 px-3 py-2 text-sm disabled:opacity-50" disabled={!selectedExecution?.id || exportMut.isPending} onClick={() => exportMut.mutate(true)}>Preview</button>
                    <button className="rounded bg-green-600 px-3 py-2 text-sm disabled:opacity-50" disabled={!selectedExecution?.id || exportMut.isPending} onClick={() => exportMut.mutate(false)}>Export</button>
                  </div>
                  {exportErrorGuide && (
                    <ExportErrorPanel
                      guide={exportErrorGuide}
                      exportPending={exportMut.isPending}
                      onOpenMapping={() => loadFile('mappings/cases.yaml')}
                      onOpenResults={() => {
                        const resultPath = executionDetail?.run.result_path
                        if (resultPath) window.electronAPI?.openPath(resultPath)
                      }}
                      onOpenSettings={() => navigate('/settings')}
                      onRetryExport={() => exportMut.mutate(false)}
                      onRetryPreview={() => exportMut.mutate(true)}
                      previewPending={exportMut.isPending}
                    />
                  )}
                  {exportPreview ? (
                    <pre className="max-h-40 overflow-auto rounded bg-slate-900 p-3 text-xs">{JSON.stringify(exportPreview, null, 2)}</pre>
                  ) : (
                    <div className="text-xs text-slate-500">Preview or export output will appear here.</div>
                  )}
                </div>
              )}

              {activePanel === 'diagnosis' && (
                <FailureDiagnosisPanel
                  execution={executionDetail?.run}
                  executionId={selectedExecution?.id || ''}
                  projectId={project.id}
                  resultPath={executionDetail?.run.result_path}
                  results={executionDetail?.results}
                  selectedAutomationKey={selectedCaseInProject?.automation_key || ''}
                  selectedCaseId={selectedCaseInProject?.id || ''}
                  summaryCases={executionDetail?.summary?.cases}
                />
              )}
            </div>
          </div>
        </div>
        <div className="w-64 bg-slate-900 rounded border border-slate-800 text-xs overflow-hidden">
          <div className="border-b border-slate-800 px-3 py-2">
            <h3 className="text-sm font-semibold">Context</h3>
          </div>
          <div className="space-y-3 overflow-auto p-3">
            <ContextSection title="Project">
              <ContextRow label="Name" value={project.name} />
              <ContextRow label="Root" value={project.root_path} />
              <ContextRow label="Generated" value={project.generated_project_path || 'Not generated'} />
            </ContextSection>

            <ContextSection title="Selected TC">
              {selectedCaseInProject ? (
                <>
                  <ContextRow label="Key" value={selectedCaseInProject.automation_key} />
                  <ContextRow label="Title" value={selectedCaseInProject.title} />
                  <ContextRow label="Status" value={selectedCaseInProject.status} />
                </>
              ) : (
                <div className="text-slate-500">No TC selected for this project.</div>
              )}
            </ContextSection>

            <ContextSection title="Run">
              <ContextRow label="Linked target" value={selectedCaseInProject?.automation_key || 'No linked TC'} />
              <ContextRow label="Status" value={runStatus} />
            </ContextSection>

            <ContextSection title="Artifacts">
              {executionDetail?.run ? (
                <>
                  <ContextRow label="Execution" value={`${executionDetail.run.run_id} (${executionDetail.run.status})`} />
                  {latestResult && <ContextRow label="Result" value={`${latestResult.automation_key} (${latestResult.status})`} />}
                  <div className="flex flex-wrap gap-2">
                    {executionDetail.run.result_path && <ArtifactButton label="Results JSON" path={executionDetail.run.result_path} />}
                    {resolvedScreenshotPath && <ArtifactButton label="Screenshot" path={resolvedScreenshotPath} />}
                    {resolvedTracePath && <ArtifactButton label="Trace" path={resolvedTracePath} />}
                  </div>
                  {!executionDetail.run.result_path && !resolvedScreenshotPath && !resolvedTracePath && (
                    <div className="text-slate-500">No artifact paths captured for the latest execution.</div>
                  )}
                  {selectedCaseInProject && !latestResult && !summaryResult && (
                    <div className="text-slate-500">No result captured for the selected TC in the latest execution.</div>
                  )}
                </>
              ) : (
                <div className="text-slate-500">No execution result loaded yet.</div>
              )}
            </ContextSection>

            <ContextSection title="Selected File">
              {selectedPath ? (
                <>
                  <ContextRow label="Path" value={selectedPath} />
                  <ContextRow label="Type" value={fileKind(selectedPath)} />
                  <ContextRow label="Language" value={editorLanguage} />
                  <ContextRow label="State" value={isDirty ? 'Unsaved' : 'Saved'} />
                </>
              ) : (
                <div className="text-slate-500">No file selected.</div>
              )}
            </ContextSection>

            <ContextSection title="Editor">
              <ContextRow label="Status" value={editorStatus} />
              <ContextRow label="Lines" value={selectedPath ? String(content.split(/\r?\n/).length) : '0'} />
              <ContextRow label="Chars" value={selectedPath ? String(content.length) : '0'} />
            </ContextSection>

            <ContextSection title="Search Results">
              {searchResults.length ? (
                searchResults.map((r: { type: string; automationKey?: string; path?: string; title?: string }, i: number) => (
                  <div key={i} className="rounded border border-slate-800 bg-slate-950 p-2">
                    <div className="font-medium text-slate-300">{r.type}</div>
                    <div className="mt-1 break-all text-slate-500">{r.automationKey || r.path || r.title}</div>
                  </div>
                ))
              ) : (
                <div className="text-slate-500">{searchQ.length > 1 ? 'No matches.' : 'Enter a search query.'}</div>
              )}
            </ContextSection>
          </div>
        </div>
      </div>
    </div>
  )
}

function ContextSection({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold uppercase text-slate-500">{title}</h4>
      <div className="space-y-2">{children}</div>
    </section>
  )
}

function ContextRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-500">{label}</div>
      <div className="break-all text-slate-300">{value}</div>
    </div>
  )
}

function ArtifactButton({ label, path }: { label: string; path: string }) {
  return (
    <button
      className="rounded bg-slate-800 px-2 py-1 text-xs text-blue-300 hover:bg-slate-700"
      type="button"
      onClick={() => window.electronAPI?.openPath(path)}
    >
      {label}
    </button>
  )
}

function PanelTab({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      className={`rounded px-3 py-1 text-xs ${active ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}
      type="button"
      onClick={onClick}
    >
      {label}
    </button>
  )
}

function ExecutionSelect({
  executions,
  onChange,
  selectedId
}: {
  executions: ExecutionRun[]
  onChange: (id: string) => void
  selectedId: string
}) {
  if (!executions.length) {
    return <div className="text-xs text-slate-500">No executions yet.</div>
  }

  return (
    <select className="rounded bg-slate-800 p-2 text-sm text-slate-200" value={selectedId} onChange={(e) => onChange(e.target.value)}>
      {executions.map((execution) => (
        <option key={execution.id} value={execution.id}>{execution.run_id} - {execution.status}</option>
      ))}
    </select>
  )
}

function SummaryGrid({ summary }: { summary: Record<string, number> }) {
  return (
    <div className="grid grid-cols-4 gap-2 text-xs">
      <SummaryCell label="Total" value={summary.total} />
      <SummaryCell label="Pass" value={summary.passed} />
      <SummaryCell label="Fail" value={summary.failed} />
      <SummaryCell label="Skip" value={summary.skipped} />
    </div>
  )
}

function SummaryCell({ label, value }: { label: string; value?: number }) {
  return (
    <div className="rounded bg-slate-900 p-2">
      <div className="text-slate-500">{label}</div>
      <div className="text-slate-200">{value ?? 0}</div>
    </div>
  )
}

function ResultTable({
  rows
}: {
  rows: Array<{
    automationKey?: string
    automation_key?: string
    error?: string | null
    status: string
    title?: string | null
  }>
}) {
  if (!rows.length) {
    return <div className="text-xs text-slate-500">No result rows loaded for this execution.</div>
  }

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-slate-500">
          <th className="py-1">Status</th>
          <th>Key</th>
          <th>Title</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${row.automationKey || row.automation_key || index}`} className="border-t border-slate-800">
            <td className="py-1 text-slate-300">{row.status}</td>
            <td className="text-slate-300">{row.automationKey || row.automation_key || '-'}</td>
            <td className="text-slate-400">{row.title || '-'}</td>
            <td className="text-red-300">{row.error || '-'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function FailureDiagnosisPanel({
  execution,
  executionId,
  projectId,
  resultPath,
  results,
  selectedAutomationKey,
  selectedCaseId,
  summaryCases
}: {
  execution?: ExecutionRun
  executionId: string
  projectId: string
  resultPath?: string
  results?: ExecutionResult[]
  selectedAutomationKey: string
  selectedCaseId: string
  summaryCases?: ExecutionSummaryCase[]
}) {
  const navigate = useNavigate()
  const appendLog = useAppStore((s) => s.appendLog)
  const clearLogs = useAppStore((s) => s.clearLogs)
  const qc = useQueryClient()
  const [actionMessage, setActionMessage] = useState('')
  const [actionOutput, setActionOutput] = useState<unknown>(null)
  const [retireConfirmations, setRetireConfirmations] = useState<Record<string, boolean>>({})
  const [generationConflict, setGenerationConflict] = useState<MaintenanceImpactSummary | null>(null)
  const [maintenanceReview, setMaintenanceReview] = useState<{
    pending:
      | { action: 'retire' | 'delete'; kind: 'retire'; row: DiagnosisRow }
      | { kind: 'raw_refresh'; row: DiagnosisRow }
    rowKey: string
    summary: MaintenanceImpactSummary
  } | null>(null)

  const diagnosisQuery = useQuery({
    queryKey: ['execution-diagnosis', projectId, executionId],
    queryFn: () => api.executions.diagnose(projectId, executionId),
    enabled: !!projectId && !!executionId,
    refetchInterval: 5000
  })

  const proposalsQuery = useQuery({
    queryKey: ['healing-proposals', projectId, selectedAutomationKey],
    queryFn: () => api.healing.list(projectId, selectedAutomationKey || undefined),
    enabled: !!projectId && !!executionId,
    refetchInterval: 5000
  })

  useEffect(() => {
    setActionMessage('')
    setActionOutput(null)
    setRetireConfirmations({})
    setMaintenanceReview(null)
    setGenerationConflict(null)
  }, [executionId])

  function showPanelGenerationConflict(error: unknown, actionLabel: string) {
    const summary = buildGenerationConflictSummary(error, actionLabel)
    if (!summary) return false
    setGenerationConflict(summary)
    setMaintenanceReview(null)
    setActionMessage(`${actionLabel} blocked by edited/conflict generated files.`)
    return true
  }

  function refreshMaintenanceState() {
    qc.invalidateQueries({ queryKey: ['executions', projectId] })
    qc.invalidateQueries({ queryKey: ['execution-detail', projectId, executionId] })
    qc.invalidateQueries({ queryKey: ['execution-diagnosis', projectId, executionId] })
    qc.invalidateQueries({ queryKey: ['healing-proposals', projectId] })
    qc.invalidateQueries({ queryKey: ['generated-files', projectId] })
  }

  const rerunMut = useMutation({
    mutationFn: async () => {
      clearLogs()
      setActionMessage('Queueing rerun-failed job...')
      setActionOutput(null)
      const res = await api.executions.rerunFailed(projectId, executionId)
      connectLogStream(res.jobId, appendLog)
      return res
    },
    onSuccess: (res) => {
      setActionMessage(`Rerun-failed queued (${res.jobId}). Watch logs in the terminal below.`)
      setActionOutput(res)
      refreshMaintenanceState()
    },
    onError: (error) => {
      setActionMessage(getApiErrorMessage(error, 'Rerun-failed failed.'))
    }
  })

  const createProposalMut = useMutation({
    mutationFn: (row: DiagnosisRow) =>
      api.executions.createHealingProposal(projectId, executionId, row.executionResultId),
    onSuccess: (res, row) => {
      setActionMessage(selectorProposalMessage(row, res.status, res.reason))
      setActionOutput(res)
      refreshMaintenanceState()
    },
    onError: (error, row) => {
      setActionMessage(`${row.automationKey}: ${getApiErrorMessage(error, 'Selector proposal failed.')}`)
    }
  })

  const acceptApplyMut = useMutation({
    mutationFn: async ({ proposalId }: { proposalId: string; row: DiagnosisRow }) => {
      const accepted = await api.healing.accept(projectId, proposalId)
      const applied = await api.healing.apply(projectId, proposalId)
      return { accepted, applied }
    },
    onSuccess: (res, variables) => {
      setActionMessage(`${variables.row.automationKey}: selector proposal accepted and applied through guarded regeneration.`)
      setActionOutput(res)
      refreshMaintenanceState()
    },
    onError: (error, variables) => {
      if (!showPanelGenerationConflict(error, `${variables.row.automationKey} guarded regeneration`)) {
        setActionMessage(`${variables.row.automationKey}: ${getApiErrorMessage(error, 'Apply failed.')}`)
      }
    }
  })

  const rejectProposalMut = useMutation({
    mutationFn: ({ proposalId }: { proposalId: string; row: DiagnosisRow }) =>
      api.healing.reject(projectId, proposalId),
    onSuccess: (res, variables) => {
      setActionMessage(`${variables.row.automationKey}: selector proposal rejected.`)
      setActionOutput(res)
      refreshMaintenanceState()
    },
    onError: (error, variables) => {
      setActionMessage(`${variables.row.automationKey}: ${getApiErrorMessage(error, 'Reject failed.')}`)
    }
  })

  const rawRefreshMut = useMutation({
    mutationFn: (row: DiagnosisRow) => {
      if (!row.caseId) throw new Error('Resolved case ID is required for selected raw refresh.')
      return api.generation.refreshWebwrightAndRegenerate(projectId, row.caseId)
    },
    onSuccess: (res, row) => {
      setActionMessage(`${row.automationKey}: selected Webwright refresh/regeneration finished.`)
      setActionOutput(res)
      setMaintenanceReview(null)
      refreshMaintenanceState()
    },
    onError: (error, row) => {
      if (!showPanelGenerationConflict(error, `${row.automationKey} raw refresh regeneration`)) {
        setActionMessage(`${row.automationKey}: ${getApiErrorMessage(error, 'Selected raw refresh failed.')}`)
      }
    }
  })

  const previewRawRefreshMut = useMutation({
    mutationFn: (row: DiagnosisRow) => {
      if (!row.caseId) throw new Error('Resolved case ID is required for maintenance preview.')
      return api.generation.previewRefreshWebwrightAndRegenerate(projectId, row.caseId)
    },
    onSuccess: (res, row) => {
      const summary = maintenanceSummaryFromRefreshPreview(res as {
        automationKey?: string
        generation?: Record<string, unknown>
        note?: string
      })
      summary.guidance = generationConflictGuidance(summary)
      setMaintenanceReview({
        rowKey: dispositionRowKey(row),
        summary,
        pending: { kind: 'raw_refresh', row }
      })
      setGenerationConflict(null)
      setActionMessage(`${row.automationKey}: review regeneration impact before applying raw refresh.`)
    },
    onError: (error, row) => {
      if (!showPanelGenerationConflict(error, `${row.automationKey} raw refresh preview`)) {
        setActionMessage(`${row.automationKey}: ${getApiErrorMessage(error, 'Maintenance preview failed.')}`)
      }
    }
  })

  const previewRetireMut = useMutation({
    mutationFn: ({ action, row }: { action: 'retire' | 'delete'; row: DiagnosisRow }) => {
      if (!row.caseId) throw new Error('Resolved case ID is required for maintenance preview.')
      return api.executions.previewRetireResult(projectId, executionId, row.executionResultId, {
        action,
        caseId: row.caseId
      })
    },
    onSuccess: (res, variables) => {
      setMaintenanceReview({
        rowKey: dispositionRowKey(variables.row),
        summary: maintenanceSummaryFromRetirePreview(res as {
          action?: string
          automationKey?: string
          cleanup?: Record<string, unknown>
        }),
        pending: { action: variables.action, kind: 'retire', row: variables.row }
      })
      setActionMessage(`${variables.row.automationKey}: review retire cleanup impact before applying.`)
    },
    onError: (error, variables) => {
      setActionMessage(`${variables.row.automationKey}: ${getApiErrorMessage(error, 'Maintenance preview failed.')}`)
    }
  })

  const retireMut = useMutation({
    mutationFn: ({ action, row }: { action: 'retire' | 'delete'; row: DiagnosisRow }) => {
      if (!row.caseId) throw new Error('Resolved case ID is required for retire/delete.')
      return api.executions.retireResult(projectId, executionId, row.executionResultId, {
        action,
        caseId: row.caseId,
        confirmed: true
      })
    },
    onSuccess: (res, variables) => {
      setActionMessage(`${variables.row.automationKey}: ${variables.action} cleanup completed.`)
      setActionOutput(res)
      setMaintenanceReview(null)
      refreshMaintenanceState()
    },
    onError: (error, variables) => {
      setActionMessage(`${variables.row.automationKey}: ${getApiErrorMessage(error, 'Retire/delete failed.')}`)
    }
  })

  if (!execution) {
    return <div className="text-xs text-slate-500">No execution result loaded for diagnosis.</div>
  }

  const rows = buildDispositionRows(
    diagnosisQuery.data?.diagnoses,
    results,
    summaryCases,
    resultPath,
    selectedAutomationKey,
    selectedCaseId
  )
  const proposalByRow = latestProposalsByResult(proposalsQuery.data || [])
  const actionPending = (
    createProposalMut.isPending ||
    acceptApplyMut.isPending ||
    rejectProposalMut.isPending ||
    previewRawRefreshMut.isPending ||
    previewRetireMut.isPending ||
    rawRefreshMut.isPending ||
    retireMut.isPending
  )

  function applyMaintenanceReview() {
    if (!maintenanceReview) return
    if (maintenanceReview.pending.kind === 'raw_refresh') {
      rawRefreshMut.mutate(maintenanceReview.pending.row)
      return
    }
    retireMut.mutate({
      action: maintenanceReview.pending.action,
      row: maintenanceReview.pending.row
    })
  }

  if (!rows.length) {
    return (
      <div className="space-y-2 text-xs">
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="font-medium text-slate-200">
            {diagnosisQuery.isError ? 'Diagnosis unavailable' : 'No classified failures found'}
          </div>
          <div className="mt-1 text-slate-500">
            {diagnosisQuery.isError
              ? getApiErrorMessage(diagnosisQuery.error, 'The Worker diagnosis endpoint did not return a result.')
              : selectedAutomationKey
                ? `No failed diagnosis is captured for ${selectedAutomationKey} in ${execution.run_id}.`
                : `No failed diagnosis is captured in ${execution.run_id}.`}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-slate-500">
          {execution.run_id} · {rows.length} diagnosable failure(s)
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="rounded bg-slate-700 px-3 py-1.5 text-xs disabled:opacity-50"
            disabled={!executionId || diagnosisQuery.isFetching}
            type="button"
            onClick={() => diagnosisQuery.refetch()}
          >
            {diagnosisQuery.isFetching ? 'Refreshing...' : 'Refresh Diagnosis'}
          </button>
          <button
            className="rounded bg-yellow-600 px-3 py-1.5 text-xs disabled:opacity-50"
            disabled={!executionId || rerunMut.isPending}
            type="button"
            onClick={() => rerunMut.mutate()}
          >
            {rerunMut.isPending ? 'Queueing...' : 'Rerun Failed'}
          </button>
        </div>
      </div>
      {actionMessage && (
        <div className="rounded border border-slate-800 bg-slate-950 p-2 text-xs text-slate-400">{actionMessage}</div>
      )}
      {generationConflict && (
        <MaintenanceImpactReview
          summary={generationConflict}
          onDismiss={() => setGenerationConflict(null)}
          onApply={() => setGenerationConflict(null)}
        />
      )}
      {maintenanceReview && (
        <MaintenanceImpactReview
          pending={rawRefreshMut.isPending || retireMut.isPending}
          summary={maintenanceReview.summary}
          onApply={applyMaintenanceReview}
          onDismiss={() => setMaintenanceReview(null)}
        />
      )}
      {actionOutput !== null && (
        <pre className="max-h-32 overflow-auto rounded border border-slate-800 bg-slate-950 p-2 text-xs text-slate-400">
          {JSON.stringify(actionOutput, null, 2)}
        </pre>
      )}
      {rows.map((row) => {
        const proposal = proposalForRow(proposalByRow, row)
        const status = proposal?.status || 'not_applicable'
        const target = row.diagnosis.target
        const rowKey = dispositionRowKey(row)
        const retireConfirmed = Boolean(retireConfirmations[rowKey])
        return (
          <div key={rowKey} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="font-medium text-slate-200">{row.automationKey}</div>
                <div className="text-xs text-slate-500">{row.title || 'Untitled TC'}</div>
                <div className="mt-1 text-[11px] text-slate-500">
                  Result {row.executionResultId} 쨌 Case {row.caseId || 'unresolved'}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`rounded px-2 py-1 text-xs ${dispositionClass(row.diagnosis.disposition)}`}>
                  {dispositionLabel(row.diagnosis.disposition)}
                </span>
                <span className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">
                  {Math.round(row.diagnosis.confidence * 100)}%
                </span>
                {proposal && <span className={`rounded px-2 py-1 text-xs ${proposalStatusClass(status)}`}>{status}</span>}
                <span className="rounded bg-red-900/40 px-2 py-1 text-xs text-red-200">{row.status}</span>
              </div>
            </div>
            <div className="mt-2 rounded bg-slate-950 p-2 text-xs text-red-200">{row.error || 'No error message captured.'}</div>
            <div className="mt-2 grid gap-2 text-xs md:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-2">
                <div className="font-medium text-slate-300">Diagnosis</div>
                <div className="mt-1 text-slate-500">{row.diagnosis.reason}</div>
                <div className="mt-2 text-slate-500">Target: {target.status} ({target.reason})</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-2">
                <div className="font-medium text-slate-300">Evidence</div>
                <CompactList label="Artifacts" values={row.diagnosis.evidence_artifact_ids} />
                <CompactList label="Selector candidates" values={row.diagnosis.selector_candidate_ids} />
                <CompactList label="Raw actions" values={target.raw_action_ids} />
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {row.screenshotPath && <ArtifactButton label="Screenshot" path={row.screenshotPath} />}
              {row.tracePath && <ArtifactButton label="Trace" path={row.tracePath} />}
              {!row.screenshotPath && !row.tracePath && (
                <span className="text-xs text-slate-500">No screenshot or trace path captured.</span>
              )}
            </div>
            <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-2 text-xs">
              <div className="font-medium text-slate-300">Recommended action</div>
              <div className="mt-1 text-slate-500">{dispositionGuidance(row.diagnosis.disposition)}</div>
              {proposal && (
                <div className="mt-2 rounded bg-slate-900 p-2">
                  <div className="text-slate-400">Proposal {proposal.id} 쨌 {proposal.kind} 쨌 {proposal.status}</div>
                  <div className="mt-1 break-all text-slate-500">Old: {proposal.old_value || '-'}</div>
                  <div className="mt-1 break-all text-slate-300">New: {proposal.new_value}</div>
                </div>
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {row.diagnosis.disposition === 'selector_changed' && (
                <>
                  <button
                    className="rounded bg-blue-700 px-3 py-1.5 text-xs disabled:opacity-50"
                    disabled={actionPending || target.status !== 'resolved'}
                    type="button"
                    onClick={() => createProposalMut.mutate(row)}
                  >
                    {proposal ? 'Refresh Proposal' : 'Create Proposal'}
                  </button>
                  <button
                    className="rounded bg-green-700 px-3 py-1.5 text-xs disabled:opacity-50"
                    disabled={actionPending || !proposal || !['proposed', 'accepted'].includes(proposal.status)}
                    type="button"
                    onClick={() => proposal && acceptApplyMut.mutate({ proposalId: proposal.id, row })}
                  >
                    Accept & Apply
                  </button>
                  <button
                    className="rounded bg-slate-700 px-3 py-1.5 text-xs disabled:opacity-50"
                    disabled={actionPending || !proposal || proposal.status !== 'proposed'}
                    type="button"
                    onClick={() => proposal && rejectProposalMut.mutate({ proposalId: proposal.id, row })}
                  >
                    Reject
                  </button>
                </>
              )}
              {row.diagnosis.disposition === 'raw_refresh_required' && (
                <button
                  className="rounded bg-purple-700 px-3 py-1.5 text-xs disabled:opacity-50"
                  disabled={actionPending || !row.caseId || target.status !== 'resolved'}
                  type="button"
                  onClick={() => previewRawRefreshMut.mutate(row)}
                >
                  {previewRawRefreshMut.isPending && maintenanceReview?.rowKey === rowKey
                    ? 'Loading preview...'
                    : 'Review Refresh Impact'}
                </button>
              )}
              {row.diagnosis.disposition === 'feature_removed_retire_tc' && (
                <>
                  <label className="flex items-center gap-2 rounded border border-amber-800/60 bg-amber-950/30 px-2 py-1.5 text-xs text-amber-100">
                    <input
                      checked={retireConfirmed}
                      type="checkbox"
                      onChange={(event) => setRetireConfirmations((current) => ({
                        ...current,
                        [rowKey]: event.target.checked
                      }))}
                    />
                    Confirm obsolete selected TC
                  </label>
                  <button
                    className="rounded bg-amber-700 px-3 py-1.5 text-xs disabled:opacity-50"
                    disabled={actionPending || !retireConfirmed || !row.caseId || target.status !== 'resolved'}
                    type="button"
                    onClick={() => previewRetireMut.mutate({ action: 'retire', row })}
                  >
                    Review Retire Impact
                  </button>
                  <button
                    className="rounded bg-red-700 px-3 py-1.5 text-xs disabled:opacity-50"
                    disabled={actionPending || !retireConfirmed || !row.caseId || target.status !== 'resolved'}
                    type="button"
                    onClick={() => previewRetireMut.mutate({ action: 'delete', row })}
                  >
                    Review Delete Impact
                  </button>
                </>
              )}
              {row.diagnosis.disposition === 'unknown' && (
                <>
                  <button className="rounded bg-slate-700 px-3 py-1.5 text-xs" type="button" onClick={() => navigate('/mapping')}>
                    Open Mapping Review
                  </button>
                  <span className="text-xs text-slate-500">Manual diagnosis only; no mutation is available for unknown failures.</span>
                </>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function FileTree({
  expandedDirs,
  nodes,
  onLoadFile,
  onToggleDir,
  selectedPath,
  depth = 0
}: {
  expandedDirs: Set<string>
  nodes: FileTreeNode[]
  onLoadFile: (path: string) => void
  onToggleDir: (path: string) => void
  selectedPath: string
  depth?: number
}) {
  return (
    <div className="space-y-1">
      {nodes.map((node) => {
        const isDirectory = node.type === 'directory'
        const isExpanded = expandedDirs.has(node.path)
        const isSelected = selectedPath === node.path
        return (
          <div key={node.path}>
            <button
              className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-slate-800 ${isSelected ? 'bg-slate-800 text-blue-300' : 'text-slate-200'}`}
              style={{ paddingLeft: `${8 + depth * 12}px` }}
              type="button"
              onClick={() => {
                if (isDirectory) onToggleDir(node.path)
                else onLoadFile(node.path)
              }}
            >
              <span className="w-4 shrink-0 text-xs text-slate-500">
                {isDirectory ? (isExpanded ? '-' : '+') : ''}
              </span>
              <span className="min-w-0 truncate">{node.name}</span>
            </button>
            {isDirectory && isExpanded && node.children.length > 0 && (
              <FileTree
                depth={depth + 1}
                expandedDirs={expandedDirs}
                nodes={node.children}
                onLoadFile={onLoadFile}
                onToggleDir={onToggleDir}
                selectedPath={selectedPath}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

function buildFileTree(items: GeneratedFileItem[]): FileTreeNode[] {
  const roots: FileTreeNode[] = []
  const byPath = new Map<string, FileTreeNode>()

  const ensureNode = (path: string, type: 'directory' | 'file') => {
    const normalized = path.replace(/\\/g, '/')
    const existing = byPath.get(normalized)
    if (existing) {
      if (type === 'directory') existing.type = 'directory'
      return existing
    }

    const parts = normalized.split('/').filter(Boolean)
    const node: FileTreeNode = {
      children: [],
      name: parts[parts.length - 1] || normalized,
      path: normalized,
      type
    }
    byPath.set(normalized, node)

    const parentPath = parts.slice(0, -1).join('/')
    if (parentPath) {
      const parent = ensureNode(parentPath, 'directory')
      parent.children.push(node)
    } else {
      roots.push(node)
    }

    return node
  }

  for (const item of items) {
    ensureNode(item.path, item.type === 'directory' ? 'directory' : 'file')
  }

  const sortNodes = (nodes: FileTreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    nodes.forEach((node) => sortNodes(node.children))
    return nodes
  }

  return sortNodes(roots)
}

function languageForPath(path: string) {
  if (path.endsWith('.py')) return 'python'
  if (path.endsWith('.yaml') || path.endsWith('.yml')) return 'yaml'
  if (path.endsWith('.json')) return 'json'
  if (path.endsWith('.md')) return 'markdown'
  if (path.endsWith('.toml')) return 'toml'
  if (path.endsWith('.ini') || path.endsWith('.cfg')) return 'ini'
  return 'plaintext'
}

function fileKind(path: string) {
  const ext = path.split('.').pop()
  return ext && ext !== path ? ext.toUpperCase() : 'File'
}

function latestExecutionRun(executions: ExecutionRun[]) {
  return [...executions].sort((a, b) => runTimeValue(b) - runTimeValue(a))[0]
}

function runTimeValue(run: ExecutionRun) {
  return Date.parse(run.created_at || run.started_at || run.ended_at || '') || 0
}

function latestResultForCase(results: ExecutionResult[] | undefined, automationKey: string) {
  return results?.find((result) => result.automation_key === automationKey)
}

function latestSummaryCaseForCase(
  cases: ExecutionSummaryCase[] | undefined,
  automationKey: string
) {
  return cases?.find((item) => (item.automationKey || item.automation_key) === automationKey)
}

function resolveArtifactPath(resultPath: string | undefined, artifactPath: string) {
  if (!artifactPath) return ''
  if (isAbsolutePath(artifactPath) || !resultPath) return artifactPath
  const normalizedResult = resultPath.replace(/\\/g, '/')
  const basePath = normalizedResult.split('/').slice(0, -1).join('/')
  return basePath ? `${basePath}/${artifactPath.replace(/\\/g, '/')}` : artifactPath
}

function isAbsolutePath(path: string) {
  return /^[A-Za-z]:[\\/]/.test(path) || path.startsWith('/') || path.startsWith('\\\\')
}

function buildDispositionRows(
  diagnoses: FailureDispositionDiagnosis[] | undefined,
  results: ExecutionResult[] | undefined,
  summaryCases: ExecutionSummaryCase[] | undefined,
  resultPath: string | undefined,
  selectedAutomationKey: string,
  selectedCaseId: string
) {
  const resultById = new Map((results || []).map((result) => [result.id, result]))
  const resultByKey = new Map((results || []).map((result) => [result.automation_key, result]))
  const summaryByKey = new Map(
    (summaryCases || [])
      .map((item) => [item.automationKey || item.automation_key || '', item] as const)
      .filter(([automationKey]) => Boolean(automationKey))
  )

  return (diagnoses || [])
    .map((diagnosis): DiagnosisRow => {
      const result = resultById.get(diagnosis.execution_result_id) ||
        (diagnosis.automation_key ? resultByKey.get(diagnosis.automation_key) : undefined)
      const automationKey = diagnosis.automation_key || diagnosis.target.automation_key || result?.automation_key || ''
      const summary = summaryByKey.get(automationKey)
      const caseId = diagnosis.target.test_case_ids[0] ||
        (selectedAutomationKey && automationKey === selectedAutomationKey ? selectedCaseId : '')
      return {
        automationKey,
        caseId,
        diagnosis,
        error: result?.error || summary?.error || '',
        executionResultId: diagnosis.execution_result_id,
        screenshotPath: resolveArtifactPath(resultPath, result?.screenshot_path || summary?.artifacts?.screenshot || ''),
        sourceCaseId: diagnosis.target.source_case_id || result?.source_case_id || '',
        sourceType: diagnosis.target.source_type || result?.source_type || '',
        status: result?.status || summary?.status || 'failed',
        title: result?.title || summary?.title || '',
        tracePath: resolveArtifactPath(resultPath, result?.trace_path || summary?.artifacts?.trace || '')
      }
    })
    .filter((row) => !selectedAutomationKey || row.automationKey === selectedAutomationKey)
}

function latestProposalsByResult(proposals: HealingProposal[]) {
  const map = new Map<string, HealingProposal>()
  const sorted = [...proposals].sort((a, b) => Date.parse(a.created_at || '') - Date.parse(b.created_at || ''))
  for (const proposal of sorted) {
    if (proposal.execution_result_id) map.set(`result:${proposal.execution_result_id}`, proposal)
    map.set(`key:${proposal.automation_key}`, proposal)
  }
  return map
}

function proposalForRow(proposals: Map<string, HealingProposal>, row: DiagnosisRow) {
  return proposals.get(`result:${row.executionResultId}`) || proposals.get(`key:${row.automationKey}`)
}

function dispositionRowKey(row: DiagnosisRow) {
  return `${row.executionResultId}:${row.automationKey}`
}

function dispositionLabel(disposition: FailureDispositionDiagnosis['disposition']) {
  if (disposition === 'selector_changed') return 'Selector changed'
  if (disposition === 'raw_refresh_required') return 'Raw refresh'
  if (disposition === 'feature_removed_retire_tc') return 'Retire TC'
  return 'Manual diagnosis'
}

function dispositionClass(disposition: FailureDispositionDiagnosis['disposition']) {
  if (disposition === 'selector_changed') return 'bg-blue-900/40 text-blue-200'
  if (disposition === 'raw_refresh_required') return 'bg-purple-900/40 text-purple-200'
  if (disposition === 'feature_removed_retire_tc') return 'bg-amber-900/40 text-amber-200'
  return 'bg-slate-800 text-slate-300'
}

function dispositionGuidance(disposition: FailureDispositionDiagnosis['disposition']) {
  if (disposition === 'selector_changed') {
    return 'Create a selector healing proposal, then accept and apply it through guarded selected regeneration.'
  }
  if (disposition === 'raw_refresh_required') {
    return 'Refresh Webwright raw only for this TC, merge the new raw actions into existing structure, then regenerate affected files.'
  }
  if (disposition === 'feature_removed_retire_tc') {
    return 'Confirm the obsolete TC before retiring or deleting it. The Worker revalidates the failed result before cleanup.'
  }
  return 'Inspect evidence manually. No code, raw, or TC mutation is offered for unknown or mixed failures.'
}

function selectorProposalMessage(row: DiagnosisRow, status: string, reason?: string) {
  if (status === 'auto_applied') return `${row.automationKey}: selector proposal auto-applied.`
  if (status === 'existing') return `${row.automationKey}: existing selector proposal loaded.`
  if (status === 'blocked') return `${row.automationKey}: selector proposal created but auto-apply was blocked (${reason || 'review required'}).`
  if (status === 'not_applicable') return `${row.automationKey}: selector proposal not applicable (${reason || 'diagnosis did not qualify'}).`
  return `${row.automationKey}: selector proposal created.`
}

function CompactList({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="mt-1">
      <span className="text-slate-500">{label}: </span>
      <span className="break-all text-slate-300">{values.length ? values.join(', ') : '-'}</span>
    </div>
  )
}

function proposalStatusClass(status: HealingProposalStatus) {
  if (status === 'accepted') return 'bg-green-900/40 text-green-200'
  if (status === 'applied') return 'bg-emerald-900/40 text-emerald-200'
  if (status === 'rejected') return 'bg-slate-800 text-slate-400'
  if (status === 'superseded') return 'bg-amber-900/40 text-amber-200'
  if (status === 'not_applicable') return 'bg-slate-800 text-slate-500'
  return 'bg-blue-900/40 text-blue-200'
}

function parseCaseIds(value: string) {
  return value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean)
}
