import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type TestCase } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

const STATUS_OPTIONS = [
  'imported',
  'webwright_pending',
  'webwright_running',
  'webwright_completed',
  'webwright_failed',
  'needs_review',
  'mapped',
  'structured',
  'generated'
] as const

const statusColor: Record<string, string> = {
  imported: 'bg-slate-600',
  webwright_pending: 'bg-slate-700',
  webwright_running: 'bg-blue-700',
  webwright_completed: 'bg-green-700',
  webwright_failed: 'bg-red-700',
  needs_review: 'bg-yellow-700',
  mapped: 'bg-blue-700',
  structured: 'bg-indigo-700',
  generated: 'bg-purple-700'
}

const inputClass = 'w-full p-2 rounded bg-slate-950 border border-slate-700 text-sm'

export function CasesPage() {
  const project = useAppStore((s) => s.currentProject)
  const storeSelectedCase = useAppStore((s) => s.selectedCase)
  const setSelectedCase = useAppStore((s) => s.setSelectedCase)
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [editStartUrl, setEditStartUrl] = useState('')
  const [editStatus, setEditStatus] = useState('imported')
  const selectedCaseId = storeSelectedCase?.project_id === project?.id ? storeSelectedCase.id : null

  const { data: cases = [], refetch, isFetching } = useQuery({
    queryKey: ['cases', project?.id],
    queryFn: () => api.cases.list(project!.id),
    enabled: !!project
  })

  const sourceTypes = useMemo(
    () => Array.from(new Set(cases.map((item) => item.source_type))).sort(),
    [cases]
  )

  const filteredCases = useMemo(() => {
    const query = search.trim().toLowerCase()
    return cases.filter((item) => {
      if (statusFilter !== 'all' && item.status !== statusFilter) return false
      if (sourceFilter !== 'all' && item.source_type !== sourceFilter) return false
      if (!query) return true
      return [
        item.title,
        item.automation_key,
        item.source_case_id,
        item.source_type,
        item.start_url || ''
      ].some((value) => value.toLowerCase().includes(query))
    })
  }, [cases, search, sourceFilter, statusFilter])

  const { data: selectedCase, isLoading: detailLoading } = useQuery({
    queryKey: ['case', project?.id, selectedCaseId],
    queryFn: () => api.cases.get(project!.id, selectedCaseId!),
    enabled: !!project && !!selectedCaseId
  })

  useEffect(() => {
    if (!selectedCase) return
    setEditStartUrl(selectedCase.start_url || '')
    setEditStatus(selectedCase.status)
  }, [selectedCase])

  const patchMut = useMutation({
    mutationFn: () => api.cases.patch(project!.id, selectedCaseId!, {
      startUrl: editStartUrl,
      status: editStatus
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['case', project?.id, selectedCaseId] })
    }
  })

  function selectCase(item: TestCase) {
    setSelectedCase(item)
  }

  if (!project) return <p>Select a project first.</p>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-bold">TC List</h2>
        <button className="px-3 py-1 bg-slate-700 rounded" type="button" onClick={() => refetch()}>
          {isFetching ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <input
          className={inputClass}
          placeholder="Search title, automation key, case id..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className={inputClass} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All statuses</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>{status}</option>
          ))}
        </select>
        <select className={inputClass} value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
          <option value="all">All sources</option>
          {sourceTypes.map((source) => (
            <option key={source} value={source}>{source}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <section className="overflow-auto rounded border border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-900 text-left text-slate-400">
                <th className="p-2">Title</th>
                <th className="p-2">Automation Key</th>
                <th className="p-2">Source</th>
                <th className="p-2">Status</th>
                <th className="p-2">Priority</th>
                <th className="p-2">Start URL</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.map((item) => (
                <tr
                  key={item.id}
                  className={`border-t border-slate-800 cursor-pointer hover:bg-slate-900/70 ${selectedCaseId === item.id ? 'bg-slate-900' : ''}`}
                  onClick={() => selectCase(item)}
                >
                  <td className="p-2">{item.title}</td>
                  <td className="p-2 font-mono text-xs">{item.automation_key}</td>
                  <td className="p-2">
                    <div>{item.source_type}</div>
                    <div className="text-xs text-slate-500">{item.source_case_id}</div>
                  </td>
                  <td className="p-2">
                    <span className={`px-2 py-0.5 rounded text-xs ${statusColor[item.status] || 'bg-slate-700'}`}>
                      {item.status}
                    </span>
                  </td>
                  <td className="p-2">{item.priority || '—'}</td>
                  <td className="p-2 max-w-xs truncate" title={item.start_url || undefined}>{item.start_url || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredCases.length === 0 && (
            <p className="p-4 text-sm text-slate-500">No cases match the current filters.</p>
          )}
        </section>

        <section className="rounded border border-slate-800 bg-slate-900 p-4 space-y-4">
          <h3 className="text-sm font-medium">Case detail</h3>
          {!selectedCaseId && <p className="text-sm text-slate-500">Select a case to view details.</p>}
          {selectedCaseId && detailLoading && <p className="text-sm text-slate-500">Loading case...</p>}
          {selectedCase && (
            <>
              <div className="space-y-1 text-sm">
                <div className="font-medium">{selectedCase.title}</div>
                <div className="text-xs text-slate-400 font-mono">{selectedCase.automation_key}</div>
                <div className="text-xs text-slate-500">{selectedCase.source_type} · {selectedCase.source_id}</div>
              </div>

              <div className="space-y-2">
                <h4 className="text-xs font-medium text-slate-400">Quick edit</h4>
                <label className="block text-xs text-slate-400">
                  Start URL
                  <input className={`${inputClass} mt-1`} value={editStartUrl} onChange={(e) => setEditStartUrl(e.target.value)} />
                </label>
                <label className="block text-xs text-slate-400">
                  Status
                  <select className={`${inputClass} mt-1`} value={editStatus} onChange={(e) => setEditStatus(e.target.value)}>
                    {STATUS_OPTIONS.map((status) => (
                      <option key={status} value={status}>{status}</option>
                    ))}
                  </select>
                </label>
                <button
                  className="px-3 py-2 bg-blue-600 rounded text-sm disabled:opacity-50"
                  disabled={patchMut.isPending}
                  type="button"
                  onClick={() => patchMut.mutate()}
                >
                  {patchMut.isPending ? 'Saving...' : 'Save changes'}
                </button>
              </div>

              {selectedCase.preconditions.length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-slate-400 mb-1">Preconditions</h4>
                  <ul className="list-disc pl-5 text-sm text-slate-300 space-y-1">
                    {selectedCase.preconditions.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <h4 className="text-xs font-medium text-slate-400 mb-1">Steps</h4>
                <ol className="list-decimal pl-5 text-sm text-slate-300 space-y-2">
                  {selectedCase.steps.map((step) => (
                    <li key={step.index}>
                      <div>{step.action}</div>
                      {step.expected && <div className="text-xs text-slate-500">Expected: {step.expected}</div>}
                    </li>
                  ))}
                </ol>
              </div>

              {selectedCase.expected_result && (
                <div>
                  <h4 className="text-xs font-medium text-slate-400 mb-1">Expected result</h4>
                  <p className="text-sm text-slate-300">{selectedCase.expected_result}</p>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
