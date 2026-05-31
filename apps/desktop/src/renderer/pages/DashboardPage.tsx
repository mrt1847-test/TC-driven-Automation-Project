import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
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
  const { data: cases = [] } = useQuery({
    queryKey: ['cases', currentProject?.id],
    queryFn: () => api.cases.list(currentProject!.id),
    enabled: !!currentProject
  })

  const createProject = useMutation({
    mutationFn: () => api.projects.create({ name: `Project ${projects.length + 1}` }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      setCurrentProject(p)
    }
  })

  const caseCounts = cases.reduce(
    (acc, testCase) => {
      const status = testCase.status.toLowerCase()
      acc.total += 1
      if (status.includes('review')) acc.needsReview += 1
      if (status.includes('generated') || status.includes('mapped')) acc.generated += 1
      return acc
    },
    { total: 0, generated: 0, needsReview: 0 }
  )
  const executionCounts = executions.reduce(
    (acc, execution) => {
      const status = execution.status.toLowerCase()
      if (status === 'passed' || status === 'pass') acc.passed += 1
      if (status === 'failed' || status === 'fail' || status === 'error') acc.failed += 1
      return acc
    },
    { passed: 0, failed: 0 }
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">Project Dashboard</h2>
          <p className="mt-1 text-sm text-slate-400">{currentProject?.name || 'Select or create a local automation project.'}</p>
        </div>
        <button
          className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
          disabled={createProject.isPending}
          onClick={() => createProject.mutate()}
        >
          {createProject.isPending ? 'Creating...' : 'New Project'}
        </button>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(16rem,22rem)_1fr]">
        <section className="space-y-3">
          <h3 className="font-semibold">Projects</h3>
          <div className="grid gap-2">
            {projects.map((p) => (
              <button
                key={p.id}
                className={`text-left p-3 rounded border ${currentProject?.id === p.id ? 'border-blue-500 bg-slate-800' : 'border-slate-700 hover:bg-slate-900'}`}
                onClick={() => setCurrentProject(p)}
              >
                <div className="font-medium">{p.name}</div>
                <div className="mt-1 truncate text-xs text-slate-400">{p.root_path}</div>
              </button>
            ))}
            {!projects.length && (
              <div className="rounded border border-dashed border-slate-700 p-4 text-sm text-slate-400">
                No projects yet.
              </div>
            )}
          </div>
        </section>

        <div className="space-y-4">
          <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
            <h3 className="font-semibold">Current Project</h3>
            {currentProject ? (
              <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-slate-500">Name</dt>
                  <dd className="mt-1">{currentProject.name}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Default Env</dt>
                  <dd className="mt-1">{currentProject.default_env}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-xs text-slate-500">Root Path</dt>
                  <dd className="mt-1 break-all text-slate-300">{currentProject.root_path}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-xs text-slate-500">Generated Project</dt>
                  <dd className="mt-1 break-all text-slate-300">{currentProject.generated_project_path || 'Not generated yet'}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-3 text-sm text-slate-400">No project selected.</p>
            )}
          </section>

          {currentProject && (
            <>
              <section className="grid gap-3 sm:grid-cols-5">
                {[
                  ['Imported', caseCounts.total],
                  ['Generated', caseCounts.generated],
                  ['Needs Review', caseCounts.needsReview],
                  ['Passed', executionCounts.passed],
                  ['Failed', executionCounts.failed]
                ].map(([label, value]) => (
                  <div key={label} className="rounded border border-slate-800 bg-slate-900/40 p-3">
                    <div className="text-xs text-slate-500">{label}</div>
                    <div className="mt-2 text-2xl font-semibold">{value}</div>
                  </div>
                ))}
              </section>

              <section className="rounded border border-slate-800 bg-slate-900/40 p-4">
                <h3 className="font-semibold">Quick Links</h3>
                <div className="mt-3 flex flex-wrap gap-2 text-sm">
                  {[
                    ['/import', 'Import TC'],
                    ['/webwright', 'Generate Raw'],
                    ['/mapping', 'Open Mapping'],
                    ['/runner', 'Runner'],
                    ['/results', 'Results']
                  ].map(([to, label]) => (
                    <Link key={to} to={to} className="rounded bg-slate-800 px-3 py-2 text-slate-200 hover:bg-slate-700">
                      {label}
                    </Link>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </div>

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
