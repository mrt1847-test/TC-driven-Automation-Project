import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function ImportPage() {
  const project = useAppStore((s) => s.currentProject)
  const qc = useQueryClient()
  const [source, setSource] = useState<'excel' | 'testrail-clone'>('excel')
  const [filePath, setFilePath] = useState('')
  const [preview, setPreview] = useState<{ preview: unknown[]; totalRows: number } | null>(null)
  const [cloneProjectId, setCloneProjectId] = useState('')

  async function pickFile() {
    const path = await window.electronAPI?.selectFile([{ name: 'Excel', extensions: ['xlsx', 'xls'] }])
    if (path) setFilePath(path)
  }

  const previewMut = useMutation({
    mutationFn: () => api.cases.previewExcel(project!.id, { file_path: filePath }),
    onSuccess: setPreview
  })

  const importMut = useMutation({
    mutationFn: () => api.cases.importExcel(project!.id, { file_path: filePath }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cases', project?.id] })
  })

  const cloneMut = useMutation({
    mutationFn: () => api.cases.importTestrailClone(project!.id, { project_id: cloneProjectId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cases', project?.id] })
  })

  if (!project) return <p>Select a project on Dashboard first.</p>

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">TC Import</h2>
      <select className="p-2 rounded bg-slate-800" value={source} onChange={(e) => setSource(e.target.value as 'excel' | 'testrail-clone')}>
        <option value="excel">Excel</option>
        <option value="testrail-clone">testrail-clone</option>
      </select>

      {source === 'excel' && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input className="flex-1 p-2 rounded bg-slate-800" value={filePath} readOnly />
            <button className="px-4 py-2 bg-slate-700 rounded" onClick={pickFile}>Browse</button>
          </div>
          <div className="flex gap-2">
            <button className="px-4 py-2 bg-blue-600 rounded" disabled={!filePath} onClick={() => previewMut.mutate()}>Preview</button>
            <button className="px-4 py-2 bg-green-600 rounded" disabled={!filePath} onClick={() => importMut.mutate()}>Import</button>
          </div>
          {preview && (
            <div>
              <p className="text-sm text-slate-400">Total rows: {preview.totalRows}</p>
              <pre className="text-xs bg-slate-900 p-2 rounded overflow-auto max-h-64">{JSON.stringify(preview.preview, null, 2)}</pre>
            </div>
          )}
        </div>
      )}

      {source === 'testrail-clone' && (
        <div className="space-y-2">
          <input className="w-full p-2 rounded bg-slate-800" placeholder="testrail-clone projectId" value={cloneProjectId} onChange={(e) => setCloneProjectId(e.target.value)} />
          <button className="px-4 py-2 bg-green-600 rounded" onClick={() => cloneMut.mutate()}>Import from testrail-clone</button>
        </div>
      )}
    </div>
  )
}
