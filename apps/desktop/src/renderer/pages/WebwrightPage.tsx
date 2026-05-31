import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, connectLogStream, type WebwrightRun } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

type AppSettings = {
  webwright?: {
    apiProvider?: string
    promptComposer?: PromptComposerSettings
    [key: string]: unknown
  }
  [key: string]: unknown
}

type PromptComposerSettings = {
  batchPrompt?: string
  caseOverrides?: Record<string, string>
}

type LlmCheckState = {
  status: 'idle' | 'ok' | 'error'
  message: string
}

const statusStyles: Record<string, string> = {
  imported: 'bg-slate-700 text-slate-100',
  pending: 'bg-slate-700 text-slate-100',
  queued: 'bg-slate-700 text-slate-100',
  webwright_running: 'bg-blue-700 text-white',
  running: 'bg-blue-700 text-white',
  webwright_completed: 'bg-green-700 text-white',
  completed: 'bg-green-700 text-white',
  webwright_failed: 'bg-red-700 text-white',
  failed: 'bg-red-700 text-white',
  cancelled: 'bg-yellow-700 text-white'
}

function statusClass(status: string) {
  return statusStyles[status] || 'bg-slate-800 text-slate-200'
}

function runTime(run?: WebwrightRun) {
  if (!run?.started_at) return 'No run'
  return new Date(run.started_at).toLocaleString()
}

function canCancel(status: string) {
  return ['queued', 'pending', 'running'].includes(status)
}

function artifactPath(outputPath: string | undefined, fileName: string) {
  if (!outputPath) return ''
  const separator = outputPath.includes('\\') ? '\\' : '/'
  return `${outputPath.replace(/[\\/]+$/, '')}${separator}${fileName}`
}

function providerLabel(provider: string) {
  return provider === 'azure-openai'
    ? 'Azure OpenAI'
    : provider.charAt(0).toUpperCase() + provider.slice(1)
}

export function WebwrightPage() {
  const project = useAppStore((s) => s.currentProject)
  const appendLog = useAppStore((s) => s.appendLog)
  const storeSelectedCase = useAppStore((s) => s.selectedCase)
  const setSelectedCase = useAppStore((s) => s.setSelectedCase)
  const [selected, setSelected] = useState<string[]>([])
  const [apiProvider, setApiProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const [llmCheck, setLlmCheck] = useState<LlmCheckState>({
    status: 'idle',
    message: 'Provider credentials not checked yet.'
  })
  const [batchPrompt, setBatchPrompt] = useState('')
  const [casePromptOverrides, setCasePromptOverrides] = useState<Record<string, string>>({})
  const [promptStatus, setPromptStatus] = useState('Prompt changes not saved yet.')
  const seededCaseIdRef = useRef<string | null>(null)
  const qc = useQueryClient()
  const selectedCaseId = storeSelectedCase?.project_id === project?.id ? storeSelectedCase.id : null

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: api.settings.get
  })
  const { data: cases = [] } = useQuery({
    queryKey: ['cases', project?.id],
    queryFn: () => api.cases.list(project!.id),
    enabled: !!project,
    refetchInterval: 3000
  })
  const { data: runs = [] } = useQuery({
    queryKey: ['webwright-runs', project?.id],
    queryFn: () => api.webwright.list(project!.id),
    enabled: !!project,
    refetchInterval: 3000
  })

  useEffect(() => {
    const savedProvider = (settings as AppSettings | undefined)?.webwright?.apiProvider
    if (savedProvider) setApiProvider(savedProvider)
    const promptComposer = (settings as AppSettings | undefined)?.webwright?.promptComposer
    setBatchPrompt(promptComposer?.batchPrompt || '')
    setCasePromptOverrides(promptComposer?.caseOverrides || {})
  }, [settings])

  useEffect(() => {
    if (!selectedCaseId || seededCaseIdRef.current === selectedCaseId) return
    if (!cases.some((c) => c.id === selectedCaseId)) return
    seededCaseIdRef.current = selectedCaseId
    setSelected((current) => current.includes(selectedCaseId) ? current : [selectedCaseId])
  }, [cases, selectedCaseId])

  const runMut = useMutation({
    mutationFn: async (caseIds: string[]) => {
      const res = await api.webwright.run(project!.id, { caseIds })
      connectLogStream(res.jobId, appendLog)
      return res
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['webwright-runs', project?.id] })
    }
  })

  const retryMut = useMutation({
    mutationFn: async (runId: string) => {
      const res = await api.webwright.retry(project!.id, runId)
      connectLogStream(res.jobId, appendLog)
      return res
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['webwright-runs', project?.id] })
    }
  })

  const cancelMut = useMutation({
    mutationFn: (runId: string) => api.webwright.cancel(project!.id, runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['webwright-runs', project?.id] })
    }
  })

  const saveLlmMut = useMutation({
    mutationFn: async () => {
      const current = (settings as AppSettings | undefined) || await api.settings.get() as AppSettings
      const next: AppSettings = {
        ...current,
        webwright: {
          ...(current.webwright || {}),
          apiProvider
        }
      }
      const saved = await api.settings.update(next) as AppSettings
      if (apiKey) {
        const stored = await window.electronAPI?.credentialSet('tc-studio', apiProvider, apiKey)
        if (!stored) throw new Error('Could not store API key in the OS credential store.')
        setApiKey('')
      }
      return saved
    },
    onSuccess: (saved) => {
      qc.setQueryData(['settings'], saved)
      qc.invalidateQueries({ queryKey: ['settings'] })
      setLlmCheck({
        status: 'ok',
        message: apiKey ? 'Provider and API key saved.' : 'Provider saved. Existing key was not changed.'
      })
    },
    onError: (error) => {
      setLlmCheck({
        status: 'error',
        message: error instanceof Error ? error.message : 'Provider credential save failed.'
      })
    }
  })

  const checkLlmMut = useMutation({
    mutationFn: async () => {
      const saved = await saveLlmMut.mutateAsync()
      await api.settings.validate()
      const storedKey = await window.electronAPI?.credentialGet('tc-studio', apiProvider)
      if (!storedKey) throw new Error(`No API key found in the OS credential store for ${providerLabel(apiProvider)}.`)
      return saved
    },
    onSuccess: () => {
      setLlmCheck({
        status: 'ok',
        message: `${providerLabel(apiProvider)} key is available in the OS credential store.`
      })
    },
    onError: (error) => {
      setLlmCheck({
        status: 'error',
        message: error instanceof Error ? error.message : 'Provider credential check failed.'
      })
    }
  })

  const savePromptMut = useMutation({
    mutationFn: async () => {
      const current = (settings as AppSettings | undefined) || await api.settings.get() as AppSettings
      const cleanedOverrides = Object.fromEntries(
        Object.entries(casePromptOverrides).filter(([, value]) => value.trim().length > 0)
      )
      const next: AppSettings = {
        ...current,
        webwright: {
          ...(current.webwright || {}),
          promptComposer: {
            batchPrompt,
            caseOverrides: cleanedOverrides
          }
        }
      }
      return api.settings.update(next) as Promise<AppSettings>
    },
    onSuccess: (saved) => {
      qc.setQueryData(['settings'], saved)
      qc.invalidateQueries({ queryKey: ['settings'] })
      setPromptStatus('Prompt composer saved.')
    },
    onError: (error) => {
      setPromptStatus(error instanceof Error ? error.message : 'Prompt composer save failed.')
    }
  })

  function runForCase(caseId: string) {
    const nextCase = cases.find((c) => c.id === caseId)
    if (nextCase) setSelectedCase(nextCase)
    setSelected([caseId])
    runMut.mutate([caseId])
  }

  function latestRun(caseId: string) {
    return runs
      .filter((r) => r.test_case_id === caseId)
      .sort((a, b) => {
        const left = Date.parse(a.started_at || a.ended_at || '')
        const right = Date.parse(b.started_at || b.ended_at || '')
        return (Number.isNaN(right) ? 0 : right) - (Number.isNaN(left) ? 0 : left)
      })[0]
  }

  if (!project) return <p>Select a project first.</p>

  const promptCase = cases.find((c) => c.id === selectedCaseId) || cases.find((c) => selected.includes(c.id))
  const caseOverride = promptCase ? casePromptOverrides[promptCase.id] || '' : ''

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Webwright Generate</h2>
        <button
          className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
          disabled={!selected.length || runMut.isPending}
          onClick={() => runMut.mutate(selected)}
        >
          {runMut.isPending ? 'Starting...' : 'Run Selected'}
        </button>
      </div>
      <section className="rounded border border-slate-800 bg-slate-900 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-44 flex-1 text-xs text-slate-400">
            LLM provider
            <select
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
              value={apiProvider}
              onChange={(e) => {
                setApiProvider(e.target.value)
                setLlmCheck({ status: 'idle', message: 'Provider credentials not checked yet.' })
              }}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="azure-openai">Azure OpenAI</option>
            </select>
          </label>
          <label className="min-w-64 flex-[2] text-xs text-slate-400">
            API key
            <input
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
              type="password"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value)
                setLlmCheck({ status: 'idle', message: 'Provider credentials not checked yet.' })
              }}
              placeholder="Stored in OS credential store"
            />
          </label>
          <button
            className="px-3 py-2 bg-slate-700 rounded text-sm disabled:opacity-50"
            disabled={saveLlmMut.isPending || checkLlmMut.isPending}
            onClick={() => saveLlmMut.mutate()}
          >
            {saveLlmMut.isPending ? 'Saving...' : 'Save LLM'}
          </button>
          <button
            className="px-3 py-2 bg-blue-600 rounded text-sm disabled:opacity-50"
            disabled={saveLlmMut.isPending || checkLlmMut.isPending}
            onClick={() => checkLlmMut.mutate()}
          >
            {checkLlmMut.isPending ? 'Checking...' : 'Check Key'}
          </button>
        </div>
        <div className={`mt-2 text-xs ${llmCheck.status === 'ok' ? 'text-green-400' : llmCheck.status === 'error' ? 'text-red-400' : 'text-slate-500'}`}>
          {llmCheck.message}
        </div>
      </section>
      <section className="rounded border border-slate-800 bg-slate-900 p-3 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium">Prompt Composer</h3>
            <p className="text-xs text-slate-500">
              {promptCase
                ? `Override target: ${promptCase.automation_key} - ${promptCase.title}`
                : 'Select a TC to edit a per-case override.'}
            </p>
          </div>
          <button
            className="px-3 py-2 bg-blue-600 rounded text-sm disabled:opacity-50"
            disabled={savePromptMut.isPending}
            onClick={() => savePromptMut.mutate()}
          >
            {savePromptMut.isPending ? 'Saving...' : 'Save Prompt'}
          </button>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <label className="block text-xs text-slate-400">
            Batch shared prompt
            <textarea
              className="mt-1 h-32 w-full resize-y rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
              value={batchPrompt}
              onChange={(e) => {
                setBatchPrompt(e.target.value)
                setPromptStatus('Prompt changes not saved yet.')
              }}
              placeholder="Shared domain hints, auth notes, selector preferences, assertion guidance..."
            />
          </label>
          <label className="block text-xs text-slate-400">
            Selected TC override
            <textarea
              className="mt-1 h-32 w-full resize-y rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 disabled:opacity-50"
              disabled={!promptCase}
              value={caseOverride}
              onChange={(e) => {
                if (!promptCase) return
                setCasePromptOverrides((current) => ({
                  ...current,
                  [promptCase.id]: e.target.value
                }))
                setPromptStatus('Prompt changes not saved yet.')
              }}
              placeholder="Extra instructions only for the selected TC..."
            />
          </label>
        </div>
        <div className="text-xs text-slate-500">{promptStatus}</div>
      </section>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-400">
            <th className="w-8"></th>
            <th className="py-2">TC</th>
            <th>Key</th>
            <th>Case Status</th>
            <th>Latest Run</th>
            <th>Run Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const run = latestRun(c.id)
            const runStatus = run?.status || 'pending'
            return (
              <tr key={c.id} className="border-t border-slate-800">
                <td><input type="checkbox" checked={selected.includes(c.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, c.id] : selected.filter((id) => id !== c.id))} /></td>
                <td className="py-2">
                  <button
                    type="button"
                    className={`text-left font-medium hover:text-blue-300 ${selectedCaseId === c.id ? 'text-blue-300' : ''}`}
                    onClick={() => setSelectedCase(c)}
                  >
                    {c.source_case_id}
                  </button>
                  <div className="text-xs text-slate-500">{c.title}</div>
                </td>
                <td>{c.automation_key}</td>
                <td><span className={`rounded px-2 py-1 text-xs ${statusClass(c.status)}`}>{c.status}</span></td>
                <td className="text-xs text-slate-400">{runTime(run)}</td>
                <td><span className={`rounded px-2 py-1 text-xs ${statusClass(runStatus)}`}>{runStatus}</span></td>
                <td className="space-x-2">
                  <button className="text-blue-400 disabled:text-slate-600" disabled={runMut.isPending} onClick={() => runForCase(c.id)}>Run</button>
                  {run && canCancel(run.status) && (
                    <button className="text-red-400 disabled:text-slate-600" disabled={cancelMut.isPending} onClick={() => cancelMut.mutate(run.id)}>Stop</button>
                  )}
                  {run?.output_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(run.output_path!)}>Folder</button>}
                  {run?.final_script_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(run.final_script_path!)}>Script</button>}
                  {run?.trajectory_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(run.trajectory_path!)}>Trajectory</button>}
                  {run?.output_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(artifactPath(run.output_path, 'stdout.log'))}>Stdout</button>}
                  {run?.output_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(artifactPath(run.output_path, 'stderr.log'))}>Stderr</button>}
                  {run?.status === 'failed' && run.id && (
                    <button className="text-yellow-400 disabled:text-slate-600" disabled={retryMut.isPending} onClick={() => retryMut.mutate(run.id)}>Retry</button>
                  )}
                </td>
              </tr>
            )
          })}
          {!cases.length && (
            <tr className="border-t border-slate-800">
              <td colSpan={7} className="py-6 text-center text-slate-400">No test cases imported yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
