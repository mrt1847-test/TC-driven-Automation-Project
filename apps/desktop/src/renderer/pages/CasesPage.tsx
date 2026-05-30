import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

const statusColor: Record<string, string> = {
  imported: 'bg-slate-600',
  webwright_completed: 'bg-green-700',
  webwright_failed: 'bg-red-700',
  needs_review: 'bg-yellow-700',
  mapped: 'bg-blue-700',
  generated: 'bg-purple-700'
}

export function CasesPage() {
  const project = useAppStore((s) => s.currentProject)
  const { data: cases = [], refetch } = useQuery({
    queryKey: ['cases', project?.id],
    queryFn: () => api.cases.list(project!.id),
    enabled: !!project
  })

  if (!project) return <p>Select a project first.</p>

  return (
    <div className="space-y-4">
      <div className="flex justify-between">
        <h2 className="text-2xl font-bold">TC List</h2>
        <button className="px-3 py-1 bg-slate-700 rounded" onClick={() => refetch()}>Refresh</button>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-400">
            <th>Case ID</th><th>Automation Key</th><th>Title</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.id} className="border-t border-slate-800">
              <td className="py-2">{c.source_case_id}</td>
              <td>{c.automation_key}</td>
              <td>{c.title}</td>
              <td><span className={`px-2 py-0.5 rounded text-xs ${statusColor[c.status] || 'bg-slate-700'}`}>{c.status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
