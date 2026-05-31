import { useEffect, useRef, useState } from 'react'
import Editor from '@monaco-editor/react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { api, connectLogStream } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function IdePage() {
  const navigate = useNavigate()
  const project = useAppStore((s) => s.currentProject)
  const selectedCase = useAppStore((s) => s.selectedCase)
  const appendLog = useAppStore((s) => s.appendLog)
  const logs = useAppStore((s) => s.logs)
  const [selectedPath, setSelectedPath] = useState('')
  const [content, setContent] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const termRef = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()

  const { data: files = [] } = useQuery({
    queryKey: ['generated-files', project?.id],
    queryFn: () => api.generation.files(project!.id),
    enabled: !!project
  })

  const { data: searchResults = [] } = useQuery({
    queryKey: ['search', project?.id, searchQ],
    queryFn: () => api.generation.search(project!.id, searchQ),
    enabled: !!project && searchQ.length > 1
  })

  const loadFile = async (path: string) => {
    if (!project) return
    const res = await api.generation.content(project.id, path)
    setSelectedPath(path)
    setContent(res.content)
  }

  const saveMut = useMutation({
    mutationFn: () => api.generation.save(project!.id, selectedPath, content),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['generated-files', project?.id] })
  })

  const generateMut = useMutation({
    mutationFn: () => api.generation.generate(project!.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['generated-files', project?.id] })
  })

  const runMut = useMutation({
    mutationFn: async () => {
      const res = await api.executions.run(project!.id, { env: 'stg', browser: 'chromium', target_type: 'all' })
      connectLogStream(res.jobId, appendLog)
    }
  })

  useEffect(() => {
    if (!termRef.current) return
    const term = new Terminal({ theme: { background: '#0f172a' }, convertEol: true })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(termRef.current)
    fit.fit()
    logs.slice(-20).forEach((l) => term.writeln(l))
    return () => term.dispose()
  }, [logs.length])

  if (!project) return <p>Select a project first.</p>

  const fileOnly = files.filter((f) => f.type === 'file')
  const selectedCaseInProject = selectedCase?.project_id === project.id ? selectedCase : null

  return (
    <div className="space-y-3 h-[calc(100vh-6rem)] flex flex-col">
      <div className="flex gap-2">
        <h2 className="text-2xl font-bold flex-1">Project IDE</h2>
        {selectedCaseInProject && (
          <button className="px-3 py-1 bg-slate-700 rounded" onClick={() => navigate('/webwright')}>
            Rerun Raw
          </button>
        )}
        <button className="px-3 py-1 bg-purple-600 rounded" onClick={() => generateMut.mutate()}>Generate Project</button>
        <button className="px-3 py-1 bg-green-600 rounded" disabled={!selectedPath} onClick={() => saveMut.mutate()}>Save</button>
        <button className="px-3 py-1 bg-blue-600 rounded" onClick={() => runMut.mutate()}>Run Linked TC</button>
      </div>

      <input className="p-2 rounded bg-slate-800" placeholder="Search automationKey / selector" value={searchQ} onChange={(e) => setSearchQ(e.target.value)} />

      <div className="flex flex-1 gap-3 min-h-0">
        <div className="w-56 bg-slate-900 rounded p-2 overflow-auto text-sm">
          {fileOnly.map((f) => (
            <button key={f.path} className={`block w-full text-left px-2 py-1 rounded hover:bg-slate-800 ${selectedPath === f.path ? 'bg-slate-800' : ''}`} onClick={() => loadFile(f.path)}>
              {f.path}
            </button>
          ))}
        </div>
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 border border-slate-700 rounded overflow-hidden">
            {selectedPath ? (
              <Editor height="100%" language={selectedPath.endsWith('.py') ? 'python' : selectedPath.endsWith('.yaml') ? 'yaml' : 'json'} value={content} onChange={(v) => setContent(v || '')} theme="vs-dark" />
            ) : (
              <div className="p-4 text-slate-400">Select a file</div>
            )}
          </div>
          <div ref={termRef} className="h-32 mt-2 rounded border border-slate-700" />
        </div>
        <div className="w-48 bg-slate-900 rounded p-2 text-xs overflow-auto">
          <h3 className="font-semibold mb-2">Context</h3>
          {searchResults.map((r: { type: string; automationKey?: string; path?: string; title?: string }, i: number) => (
            <div key={i} className="mb-1">{r.type}: {r.automationKey || r.path || r.title}</div>
          ))}
        </div>
      </div>
    </div>
  )
}
