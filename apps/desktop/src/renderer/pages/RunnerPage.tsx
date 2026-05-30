import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, connectLogStream } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function RunnerPage() {
  const project = useAppStore((s) => s.currentProject)
  const appendLog = useAppStore((s) => s.appendLog)
  const clearLogs = useAppStore((s) => s.clearLogs)
  const logs = useAppStore((s) => s.logs)
  const [env, setEnv] = useState('stg')
  const [browser, setBrowser] = useState('chromium')
  const [headed, setHeaded] = useState(false)
  const [target, setTarget] = useState('all')
  const [automationKey, setAutomationKey] = useState('')

  const runMut = useMutation({
    mutationFn: async () => {
      clearLogs()
      const res = await api.executions.run(project!.id, {
        env,
        browser,
        headed,
        target_type: target,
        automation_key: target === 'case' ? automationKey : undefined
      })
      connectLogStream(res.jobId, appendLog)
    }
  })

  if (!project) return <p>Select a project first.</p>

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Runner</h2>
      <div className="grid grid-cols-2 gap-4 max-w-xl">
        <label>Environment<select className="w-full p-2 rounded bg-slate-800 mt-1" value={env} onChange={(e) => setEnv(e.target.value)}><option>local</option><option>stg</option><option>prod</option></select></label>
        <label>Browser<select className="w-full p-2 rounded bg-slate-800 mt-1" value={browser} onChange={(e) => setBrowser(e.target.value)}><option>chromium</option><option>firefox</option><option>webkit</option></select></label>
        <label>Target<select className="w-full p-2 rounded bg-slate-800 mt-1" value={target} onChange={(e) => setTarget(e.target.value)}><option value="all">All</option><option value="case">Selected case</option></select></label>
        <label className="flex items-center gap-2 mt-6"><input type="checkbox" checked={headed} onChange={(e) => setHeaded(e.target.checked)} /> Headed</label>
      </div>
      {target === 'case' && (
        <input className="w-full max-w-md p-2 rounded bg-slate-800" placeholder="automationKey" value={automationKey} onChange={(e) => setAutomationKey(e.target.value)} />
      )}
      <button className="px-4 py-2 bg-green-600 rounded" onClick={() => runMut.mutate()}>Run</button>
      <pre className="bg-slate-900 p-3 rounded text-xs max-h-96 overflow-auto">{logs.join('\n') || 'Logs will appear here...'}</pre>
    </div>
  )
}
