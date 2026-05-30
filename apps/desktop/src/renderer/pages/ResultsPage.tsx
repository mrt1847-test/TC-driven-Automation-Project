import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function ResultsPage() {
  const project = useAppStore((s) => s.currentProject)
  const [selectedExec, setSelectedExec] = useState('')

  const { data: executions = [] } = useQuery({
    queryKey: ['executions', project?.id],
    queryFn: () => api.executions.list(project!.id),
    enabled: !!project
  })

  const execId = selectedExec || executions[0]?.id
  const { data: detail } = useQuery({
    queryKey: ['execution-detail', project?.id, execId],
    queryFn: () => api.executions.get(project!.id, execId),
    enabled: !!project && !!execId,
    refetchInterval: 5000
  })

  if (!project) return <p>Select a project first.</p>

  const summary = detail?.summary

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Execution Results</h2>
      <select className="p-2 rounded bg-slate-800" value={execId || ''} onChange={(e) => setSelectedExec(e.target.value)}>
        {executions.map((e) => <option key={e.id} value={e.id}>{e.run_id} — {e.status}</option>)}
      </select>

      {summary && (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-slate-900 p-3 rounded">Total: {summary.summary?.total}</div>
          <div className="bg-green-900/40 p-3 rounded">Pass: {summary.summary?.passed}</div>
          <div className="bg-red-900/40 p-3 rounded">Fail: {summary.summary?.failed}</div>
          <div className="bg-slate-900 p-3 rounded">Skip: {summary.summary?.skipped}</div>
        </div>
      )}

      <table className="w-full text-sm">
        <thead><tr className="text-left text-slate-400"><th>Status</th><th>Key</th><th>Title</th><th>Error</th></tr></thead>
        <tbody>
          {(summary?.cases || detail?.results || []).map((c: { automationKey?: string; automation_key?: string; title?: string; status: string; error?: string }, i: number) => (
            <tr key={i} className="border-t border-slate-800">
              <td className="py-2">{c.status}</td>
              <td>{c.automationKey || c.automation_key}</td>
              <td>{c.title}</td>
              <td className="text-red-400 text-xs">{c.error || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
