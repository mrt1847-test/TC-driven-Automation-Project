import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function DashboardPage() {
  const qc = useQueryClient()
  const setCurrentProject = useAppStore((s) => s.setCurrentProject)
  const currentProject = useAppStore((s) => s.currentProject)

  const { data: projects = [] } = useQuery({ queryKey: ['projects'], queryFn: api.projects.list })
  const { data: executions = [] } = useQuery({
    queryKey: ['executions', currentProject?.id],
    queryFn: () => api.executions.list(currentProject!.id),
    enabled: !!currentProject
  })

  const createProject = useMutation({
    mutationFn: () => api.projects.create({ name: `Project ${projects.length + 1}` }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      setCurrentProject(p)
    }
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Project Dashboard</h2>
        <button className="px-4 py-2 bg-blue-600 rounded" onClick={() => createProject.mutate()}>New Project</button>
      </div>

      <section>
        <h3 className="font-semibold mb-2">Projects</h3>
        <div className="grid gap-2">
          {projects.map((p) => (
            <button
              key={p.id}
              className={`text-left p-3 rounded border ${currentProject?.id === p.id ? 'border-blue-500 bg-slate-800' : 'border-slate-700'}`}
              onClick={() => setCurrentProject(p)}
            >
              <div className="font-medium">{p.name}</div>
              <div className="text-xs text-slate-400">{p.root_path}</div>
            </button>
          ))}
        </div>
      </section>

      {currentProject && (
        <section>
          <h3 className="font-semibold mb-2">Recent Runs</h3>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-400"><th>Run ID</th><th>Env</th><th>Status</th></tr></thead>
            <tbody>
              {executions.slice(0, 5).map((e) => (
                <tr key={e.id} className="border-t border-slate-800">
                  <td className="py-2">{e.run_id}</td>
                  <td>{e.env}</td>
                  <td>{e.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}
