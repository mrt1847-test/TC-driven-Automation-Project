import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, connectLogStream, type LogStreamStatus } from '@/lib/api'
import { LogStreamPanel } from '@/components/LogStreamPanel'
import { useAppStore } from '@/store/appStore'

export function RunnerPage() {
  const project = useAppStore((s) => s.currentProject)
  const selectedCase = useAppStore((s) => s.selectedCase)
  const appendLog = useAppStore((s) => s.appendLog)
  const clearLogs = useAppStore((s) => s.clearLogs)
  const logs = useAppStore((s) => s.logs)
  const [env, setEnv] = useState('stg')
  const [browser, setBrowser] = useState('chromium')
  const [headed, setHeaded] = useState(false)
  const [target, setTarget] = useState('all')
  const [automationKey, setAutomationKey] = useState('')
  const [caseIds, setCaseIds] = useState('')
  const [resultTarget, setResultTarget] = useState('local')
  const [runStatus, setRunStatus] = useState('No run started.')
  const [streaming, setStreaming] = useState(false)
  const [runtimeStatus, setRuntimeStatus] = useState('')

  useEffect(() => {
    if (project?.default_env) setEnv(project.default_env)
  }, [project?.default_env, project?.id])

  useEffect(() => {
    if (selectedCase?.project_id !== project?.id || !selectedCase.automation_key) return
    setTarget('case')
    setAutomationKey(selectedCase.automation_key)
  }, [project?.id, selectedCase?.automation_key, selectedCase?.project_id])

  function handleStreamStatus(status: LogStreamStatus) {
    if (status === 'open') {
      setStreaming(true)
      setRunStatus('Streaming runner logs...')
      return
    }
    if (status === 'closed' || status === 'error') {
      setStreaming(false)
      setRunStatus(status === 'error' ? 'Log stream error.' : 'Run log stream closed.')
    }
  }

  const runMut = useMutation({
    mutationFn: async () => {
      clearLogs()
      setStreaming(false)
      setRunStatus('Queueing runner job...')
      const res = await api.executions.run(project!.id, {
        env,
        browser,
        headed,
        target_type: target,
        automation_key: target === 'case' ? automationKey : undefined,
        case_ids: target === 'selected' ? parseCaseIds(caseIds) : undefined,
        result_target: resultTarget
      })
      connectLogStream(res.jobId, appendLog, handleStreamStatus)
      return res.jobId
    },
    onSuccess: (jobId) => {
      setRunStatus(`Queued ${jobId}`)
    },
    onError: (error) => {
      setStreaming(false)
      setRunStatus(error instanceof Error ? error.message : 'Run failed.')
    }
  })

  async function installRuntime() {
    if (!project?.generated_project_path) {
      setRuntimeStatus('Generate a project first.')
      return
    }
    setRuntimeStatus('Installing Python deps and Chromium...')
    try {
      const res = await api.installDeps(project.id, project.generated_project_path)
      setRuntimeStatus(res.ok ? 'Runtime ready.' : `Install failed: ${res.pipError || res.message || 'unknown'}`)
    } catch (error) {
      setRuntimeStatus(error instanceof Error ? error.message : 'Install failed.')
    }
  }

  if (!project) return <p>Select a project first.</p>

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Runner</h2>
      <div className="grid grid-cols-2 gap-4 max-w-xl">
        <label>Environment<select className="w-full p-2 rounded bg-slate-800 mt-1" value={env} onChange={(e) => setEnv(e.target.value)}><option>local</option><option>stg</option><option>prod</option></select></label>
        <label>Browser<select className="w-full p-2 rounded bg-slate-800 mt-1" value={browser} onChange={(e) => setBrowser(e.target.value)}><option>chromium</option><option>firefox</option><option>webkit</option></select></label>
        <label>Target<select className="w-full p-2 rounded bg-slate-800 mt-1" value={target} onChange={(e) => setTarget(e.target.value)}><option value="all">All</option><option value="case">Automation key</option><option value="selected">Case IDs</option></select></label>
        <label>Result Target<select className="w-full p-2 rounded bg-slate-800 mt-1" value={resultTarget} onChange={(e) => setResultTarget(e.target.value)}><option value="local">local only</option><option value="testrail-clone">testrail-clone</option><option value="testrail">TestRail</option><option value="excel">Excel</option><option value="google-sheets">Google Sheets</option></select></label>
        <label className="flex items-center gap-2 mt-6"><input type="checkbox" checked={headed} onChange={(e) => setHeaded(e.target.checked)} /> Headed</label>
      </div>
      {target === 'case' && (
        <input className="w-full max-w-md p-2 rounded bg-slate-800" placeholder="automationKey" value={automationKey} onChange={(e) => setAutomationKey(e.target.value)} />
      )}
      {target === 'selected' && (
        <textarea className="w-full max-w-md p-2 rounded bg-slate-800" placeholder="case IDs or automation keys, comma/newline separated" rows={3} value={caseIds} onChange={(e) => setCaseIds(e.target.value)} />
      )}
      <div className="text-xs text-slate-500">{runStatus}</div>
      {runtimeStatus && <div className="text-xs text-slate-400">{runtimeStatus}</div>}
      <div className="flex gap-2">
      <button
        type="button"
        className="px-4 py-2 bg-slate-700 rounded disabled:opacity-50"
        disabled={!project.generated_project_path}
        onClick={installRuntime}
      >
        Install Runtime
      </button>
      <button
        className="px-4 py-2 bg-green-600 rounded disabled:opacity-50"
        disabled={runMut.isPending || (target === 'case' && !automationKey) || (target === 'selected' && parseCaseIds(caseIds).length === 0)}
        onClick={() => runMut.mutate()}
      >
        {runMut.isPending ? 'Running...' : 'Run'}
      </button>
      </div>
      <LogStreamPanel
        logs={logs}
        streaming={streaming}
        onClear={clearLogs}
        emptyMessage="Run a job to stream stdout/stderr here via /ws/logs/{job_id}."
      />
    </div>
  )
}

function parseCaseIds(value: string) {
  return value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean)
}
