import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function MappingPage() {
  const project = useAppStore((s) => s.currentProject)
  const [caseId, setCaseId] = useState('')
  const qc = useQueryClient()

  const { data: cases = [] } = useQuery({
    queryKey: ['cases', project?.id],
    queryFn: () => api.cases.list(project!.id),
    enabled: !!project
  })

  const selectedCase = cases.find((c) => c.id === caseId) || cases[0]

  const { data: actions = [] } = useQuery({
    queryKey: ['actions', project?.id, selectedCase?.id],
    queryFn: () => api.mapping.actions(project!.id, selectedCase!.id),
    enabled: !!project && !!selectedCase
  })

  const { data: mappings = [] } = useQuery({
    queryKey: ['mappings', project?.id, selectedCase?.id],
    queryFn: () => api.mapping.get(project!.id, selectedCase!.id),
    enabled: !!project && !!selectedCase
  })

  const normalizeMut = useMutation({
    mutationFn: () => api.mapping.normalize(project!.id, selectedCase!.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mappings', project?.id, selectedCase?.id] })
  })

  if (!project) return <p>Select a project first.</p>

  const steps = selectedCase ? JSON.parse(selectedCase.steps_json || '[]') : []

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Mapping & Review</h2>
      <select className="p-2 rounded bg-slate-800" value={selectedCase?.id || ''} onChange={(e) => setCaseId(e.target.value)}>
        {cases.map((c) => <option key={c.id} value={c.id}>{c.automation_key} — {c.title}</option>)}
      </select>
      <button className="px-4 py-2 bg-blue-600 rounded" onClick={() => normalizeMut.mutate()}>Auto Map</button>

      <div className="grid grid-cols-3 gap-4 min-h-64">
        <div className="bg-slate-900 p-3 rounded">
          <h3 className="font-semibold mb-2">TC Steps</h3>
          {steps.map((s: { index: number; action: string; expected?: string }) => (
            <div key={s.index} className="mb-2 text-sm border-b border-slate-800 pb-1">
              <div>{s.index}. {s.action}</div>
              {s.expected && <div className="text-slate-400 text-xs">{s.expected}</div>}
            </div>
          ))}
        </div>
        <div className="bg-slate-900 p-3 rounded">
          <h3 className="font-semibold mb-2">Raw Actions</h3>
          {actions.map((a: { id: string; type: string; selector?: string; target?: string }) => (
            <div key={a.id} className="mb-2 text-sm">
              <span className="text-blue-400">{a.type}</span> {a.selector || a.target}
            </div>
          ))}
        </div>
        <div className="bg-slate-900 p-3 rounded">
          <h3 className="font-semibold mb-2">Normalized Flow</h3>
          {mappings.map((m: { tc_step_index: number; normalized_step_name?: string; status: string }) => (
            <div key={m.tc_step_index} className="mb-2 text-sm">
              step {m.tc_step_index}: {m.normalized_step_name || '—'} ({m.status})
            </div>
          ))}
          {selectedCase?.status === 'needs_review' && (
            <p className="text-yellow-400 text-xs mt-2">needs_review — step/action count mismatch</p>
          )}
        </div>
      </div>
    </div>
  )
}
