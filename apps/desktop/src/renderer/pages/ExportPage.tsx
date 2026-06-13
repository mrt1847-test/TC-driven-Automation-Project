import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function ExportPage() {
  const project = useAppStore((s) => s.currentProject)
  const [target, setTarget] = useState('testrail-clone')
  const [preview, setPreview] = useState<unknown>(null)
  const [execId, setExecId] = useState('')

  const { data: executions = [] } = useQuery({
    queryKey: ['executions', project?.id],
    queryFn: () => api.executions.list(project!.id),
    enabled: !!project
  })

  async function runExport(doPreview: boolean) {
    const executionId = execId || executions[0]?.id
    if (!project || !executionId) throw new Error('Select an execution first.')
    if (target === 'testrail' && window.electronAPI?.testrailExport) {
      const result = await window.electronAPI.testrailExport(project.id, executionId, doPreview)
      if (!result.ok) throw new Error(result.message)
      return result.result
    }
    if (target === 'google-sheets' && window.electronAPI?.googleSheetsExport) {
      const result = await window.electronAPI.googleSheetsExport(project.id, executionId, doPreview)
      if (!result.ok) throw new Error(result.message)
      return result.result
    }
    const config = ['testrail', 'google-sheets'].includes(target) && !doPreview ? { mock: true } : undefined
    return api.executions.export(project.id, executionId, target, doPreview, config)
  }

  const exportMut = useMutation({
    mutationFn: (doPreview: boolean) => runExport(doPreview)
  })

  if (!project) return <p>Select a project first.</p>

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Result Export</h2>
      <select className="p-2 rounded bg-slate-800" value={execId || executions[0]?.id || ''} onChange={(e) => setExecId(e.target.value)}>
        {executions.map((e) => <option key={e.id} value={e.id}>{e.run_id}</option>)}
      </select>
      <select className="p-2 rounded bg-slate-800 ml-2" value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="testrail-clone">testrail-clone</option>
        <option value="testrail">TestRail</option>
        <option value="excel">Excel</option>
        <option value="google-sheets">Google Sheets</option>
      </select>
      <div className="flex gap-2">
        <button className="px-4 py-2 bg-slate-700 rounded" onClick={async () => setPreview(await exportMut.mutateAsync(true))}>Preview</button>
        <button className="px-4 py-2 bg-green-600 rounded" onClick={async () => setPreview(await exportMut.mutateAsync(false))}>Export</button>
      </div>
      {preview && <pre className="text-xs bg-slate-900 p-3 rounded overflow-auto">{JSON.stringify(preview, null, 2)}</pre>}
    </div>
  )
}
