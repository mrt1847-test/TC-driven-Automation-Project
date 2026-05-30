import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, connectLogStream } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function WebwrightPage() {
  const project = useAppStore((s) => s.currentProject)
  const appendLog = useAppStore((s) => s.appendLog)
  const [selected, setSelected] = useState<string[]>([])
  const qc = useQueryClient()

  const { data: cases = [] } = useQuery({
    queryKey: ['cases', project?.id],
    queryFn: () => api.cases.list(project!.id),
    enabled: !!project
  })
  const { data: runs = [] } = useQuery({
    queryKey: ['webwright-runs', project?.id],
    queryFn: () => api.webwright.list(project!.id),
    enabled: !!project,
    refetchInterval: 3000
  })

  const runMut = useMutation({
    mutationFn: async () => {
      const res = await api.webwright.run(project!.id, { caseIds: selected })
      connectLogStream(res.jobId, appendLog)
      return res
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webwright-runs', project?.id] })
  })

  function runForCase(caseId: string) {
    setSelected([caseId])
    runMut.mutate()
  }

  function latestRun(caseId: string) {
    return runs.find((r) => r.test_case_id === caseId)
  }

  if (!project) return <p>Select a project first.</p>

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Webwright Generate</h2>
        <button className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50" disabled={!selected.length} onClick={() => runMut.mutate()}>Run Selected</button>
      </div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-slate-400"><th></th><th>TC</th><th>Key</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>
          {cases.map((c) => {
            const run = latestRun(c.id)
            return (
              <tr key={c.id} className="border-t border-slate-800">
                <td><input type="checkbox" checked={selected.includes(c.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, c.id] : selected.filter((id) => id !== c.id))} /></td>
                <td>{c.source_case_id}</td>
                <td>{c.automation_key}</td>
                <td>{run?.status || c.status}</td>
                <td className="space-x-2">
                  <button className="text-blue-400" onClick={() => runForCase(c.id)}>Run</button>
                  {run?.output_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(run.output_path!)}>Open Folder</button>}
                  {run?.status === 'failed' && run.id && (
                    <button className="text-yellow-400" onClick={() => api.webwright.retry(project.id, run.id)}>Retry</button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
