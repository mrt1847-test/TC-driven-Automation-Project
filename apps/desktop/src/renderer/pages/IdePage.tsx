import { useEffect, useRef, useState, type ReactNode } from 'react'
import Editor from '@monaco-editor/react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { api, connectLogStream, type ExecutionResult, type ExecutionRun } from '@/lib/api'
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
  automationKey: string
  error: string
  screenshotPath: string
  status: string
  title: string
  tracePath: string
}

type HealingProposalStatus = 'proposed' | 'accepted' | 'rejected'

export function IdePage() {
  const navigate = useNavigate()
  const project = useAppStore((s) => s.currentProject)
  const selectedCase = useAppStore((s) => s.selectedCase)
  const appendLog = useAppStore((s) => s.appendLog)
  const logs = useAppStore((s) => s.logs)
  const [selectedPath, setSelectedPath] = useState('')
  const [content, setContent] = useState('')
  const [savedContent, setSavedContent] = useState('')
  const [loadingPath, setLoadingPath] = useState('')
  const [editorStatus, setEditorStatus] = useState('Select a generated file.')
  const [runStatus, setRunStatus] = useState('No IDE run started.')
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

  const generateMut = useMutation({
    mutationFn: () => api.generation.generate(project!.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['generated-files', project?.id] })
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

  const exportMut = useMutation({
    mutationFn: (preview: boolean) => {
      if (!project || !selectedExecution?.id) throw new Error('Select an execution first.')
      return api.executions.export(project.id, selectedExecution.id, exportTarget, preview)
    },
    onSuccess: (result) => setExportPreview(result),
    onError: (error) => setExportPreview(error instanceof Error ? { error: error.message } : { error: 'Export failed.' })
  })

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
  const diagnosisRows = buildDiagnosisRows(
    executionDetail?.results,
    executionDetail?.summary?.cases,
    executionDetail?.run.result_path
  )
  const selectedDiagnosisRows = selectedCaseInProject
    ? diagnosisRows.filter((row) => row.automationKey === selectedCaseInProject.automation_key)
    : diagnosisRows

  return (
    <div className="space-y-3 h-[calc(100vh-6rem)] flex flex-col">
      <div className="flex gap-2">
        <h2 className="text-2xl font-bold flex-1">Project IDE</h2>
        {selectedCaseInProject && (
          <button className="px-3 py-1 bg-slate-700 rounded" onClick={() => navigate('/webwright')}>
            Rerun Raw
          </button>
        )}
        <button className="px-3 py-1 bg-purple-600 rounded" onClick={() => generateMut.mutate()}>Generate Project</button>
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
                  <button
                    className="rounded bg-green-600 px-3 py-2 text-sm disabled:opacity-50"
                    disabled={
                      runMut.isPending ||
                      (runnerTarget === 'linked' && !runnerAutomationKey && !selectedCaseInProject) ||
                      (runnerTarget === 'selected' && parseCaseIds(runnerCaseIds).length === 0)
                    }
                    type="button"
                    onClick={() => runMut.mutate({
                      automationKey: runnerAutomationKey || selectedCaseInProject?.automation_key,
                      browser: runnerBrowser,
                      caseIds: parseCaseIds(runnerCaseIds),
                      env: runnerEnv,
                      headed: runnerHeaded,
                      resultTarget: runnerResultTarget,
                      target: runnerTarget
                    })}
                  >
                    {runMut.isPending ? 'Running...' : 'Run'}
                  </button>
                </div>
              )}

              {activePanel === 'results' && (
                <div className="space-y-3">
                  <ExecutionSelect executions={executions} selectedId={selectedExecution?.id || ''} onChange={setSelectedExecutionId} />
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
                  rows={selectedDiagnosisRows}
                  selectedAutomationKey={selectedCaseInProject?.automation_key || ''}
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
  rows,
  selectedAutomationKey
}: {
  execution?: ExecutionRun
  executionId: string
  projectId: string
  rows: DiagnosisRow[]
  selectedAutomationKey: string
}) {
  const appendLog = useAppStore((s) => s.appendLog)
  const clearLogs = useAppStore((s) => s.clearLogs)
  const qc = useQueryClient()
  const [proposalStates, setProposalStates] = useState<Record<string, HealingProposalStatus>>({})
  const [actionMessage, setActionMessage] = useState('')

  useEffect(() => {
    setProposalStates({})
    setActionMessage('')
  }, [executionId])

  const rerunMut = useMutation({
    mutationFn: async () => {
      clearLogs()
      setActionMessage('Queueing rerun-failed job...')
      const res = await api.executions.rerunFailed(projectId, executionId)
      connectLogStream(res.jobId, appendLog)
      return res
    },
    onSuccess: (res) => {
      setActionMessage(`Rerun-failed queued (${res.jobId}). Watch logs in the terminal below.`)
      qc.invalidateQueries({ queryKey: ['executions', projectId] })
      qc.invalidateQueries({ queryKey: ['execution-detail', projectId, executionId] })
    },
    onError: (error) => {
      setActionMessage(error instanceof Error ? error.message : 'Rerun-failed failed.')
    }
  })

  function proposalKey(row: DiagnosisRow) {
    return `${executionId}:${row.automationKey}`
  }

  function proposalStatus(row: DiagnosisRow): HealingProposalStatus {
    return proposalStates[proposalKey(row)] || 'proposed'
  }

  function acceptProposal(row: DiagnosisRow) {
    setProposalStates((current) => ({ ...current, [proposalKey(row)]: 'accepted' }))
    setActionMessage(`${row.automationKey}: proposal accepted locally. Structured apply/regenerate will use worker healing APIs when C12-06 lands.`)
  }

  function rejectProposal(row: DiagnosisRow) {
    setProposalStates((current) => ({ ...current, [proposalKey(row)]: 'rejected' }))
    setActionMessage(`${row.automationKey}: proposal rejected.`)
  }

  if (!execution) {
    return <div className="text-xs text-slate-500">No execution result loaded for diagnosis.</div>
  }

  if (!rows.length) {
    return (
      <div className="space-y-2 text-xs">
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="font-medium text-slate-200">No failures found</div>
          <div className="mt-1 text-slate-500">
            {selectedAutomationKey
              ? `No failed result is captured for ${selectedAutomationKey} in ${execution.run_id}.`
              : `No failed result is captured in ${execution.run_id}.`}
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
        <button
          className="rounded bg-yellow-600 px-3 py-1.5 text-xs disabled:opacity-50"
          disabled={!executionId || rerunMut.isPending}
          type="button"
          onClick={() => rerunMut.mutate()}
        >
          {rerunMut.isPending ? 'Queueing...' : 'Rerun Failed'}
        </button>
      </div>
      {actionMessage && (
        <div className="rounded border border-slate-800 bg-slate-950 p-2 text-xs text-slate-400">{actionMessage}</div>
      )}
      {rows.map((row) => {
        const status = proposalStatus(row)
        const kind = proposalKind(row)
        return (
          <div key={`${row.automationKey}-${row.title}`} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="font-medium text-slate-200">{row.automationKey}</div>
                <div className="text-xs text-slate-500">{row.title || 'Untitled TC'}</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">{kind}</span>
                <span className={`rounded px-2 py-1 text-xs ${proposalStatusClass(status)}`}>{status}</span>
                <span className="rounded bg-red-900/40 px-2 py-1 text-xs text-red-200">{row.status}</span>
              </div>
            </div>
            <div className="mt-2 rounded bg-slate-950 p-2 text-xs text-red-200">{row.error || 'No error message captured.'}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {row.screenshotPath && <ArtifactButton label="Screenshot" path={row.screenshotPath} />}
              {row.tracePath && <ArtifactButton label="Trace" path={row.tracePath} />}
              {!row.screenshotPath && !row.tracePath && (
                <span className="text-xs text-slate-500">No screenshot or trace path captured.</span>
              )}
            </div>
            <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-2 text-xs">
              <div className="font-medium text-slate-300">Healing proposal</div>
              <div className="mt-1 text-slate-500">{diagnosisProposal(row)}</div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                className="rounded bg-green-700 px-3 py-1.5 text-xs disabled:opacity-50"
                disabled={status !== 'proposed'}
                type="button"
                onClick={() => acceptProposal(row)}
              >
                Accept
              </button>
              <button
                className="rounded bg-slate-700 px-3 py-1.5 text-xs disabled:opacity-50"
                disabled={status !== 'proposed'}
                type="button"
                onClick={() => rejectProposal(row)}
              >
                Reject
              </button>
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

function buildDiagnosisRows(
  results: ExecutionResult[] | undefined,
  summaryCases: ExecutionSummaryCase[] | undefined,
  resultPath: string | undefined
) {
  const rows = new Map<string, DiagnosisRow>()

  for (const result of results || []) {
    if (!isFailureStatus(result.status)) continue
    rows.set(result.automation_key, {
      automationKey: result.automation_key,
      error: result.error || '',
      screenshotPath: resolveArtifactPath(resultPath, result.screenshot_path || ''),
      status: result.status,
      title: result.title || '',
      tracePath: resolveArtifactPath(resultPath, result.trace_path || '')
    })
  }

  for (const item of summaryCases || []) {
    if (!isFailureStatus(item.status)) continue
    const automationKey = item.automationKey || item.automation_key || ''
    if (!automationKey) continue
    const existing = rows.get(automationKey)
    rows.set(automationKey, {
      automationKey,
      error: existing?.error || item.error || '',
      screenshotPath: existing?.screenshotPath || resolveArtifactPath(resultPath, item.artifacts?.screenshot || ''),
      status: existing?.status || item.status,
      title: existing?.title || item.title || '',
      tracePath: existing?.tracePath || resolveArtifactPath(resultPath, item.artifacts?.trace || '')
    })
  }

  return [...rows.values()]
}

function isFailureStatus(status: string) {
  const normalized = status.toLowerCase()
  return normalized.includes('fail') || normalized.includes('error')
}

function diagnosisProposal(row: DiagnosisRow) {
  const lowerError = row.error.toLowerCase()
  if (lowerError.includes('timeout')) {
    return 'Inspect the trace timing and screenshot state, then consider a more stable wait or selector in the generated step.'
  }
  if (lowerError.includes('selector') || lowerError.includes('locator')) {
    return 'Compare the failed locator against the screenshot/trace evidence and prepare a selector replacement before regeneration.'
  }
  if (lowerError.includes('assert') || lowerError.includes('expect')) {
    return 'Check whether the generated assertion still matches the TC expected result and captured page state.'
  }
  return 'Review the captured error with available screenshot/trace evidence and prepare a focused generated-code or selector fix.'
}

function proposalKind(row: DiagnosisRow) {
  const lowerError = row.error.toLowerCase()
  if (lowerError.includes('selector') || lowerError.includes('locator')) return 'selector_replace'
  if (lowerError.includes('timeout')) return 'wait_adjustment'
  if (lowerError.includes('assert') || lowerError.includes('expect')) return 'assertion_review'
  return 'manual_review'
}

function proposalStatusClass(status: HealingProposalStatus) {
  if (status === 'accepted') return 'bg-green-900/40 text-green-200'
  if (status === 'rejected') return 'bg-slate-800 text-slate-400'
  return 'bg-blue-900/40 text-blue-200'
}

function parseCaseIds(value: string) {
  return value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean)
}
