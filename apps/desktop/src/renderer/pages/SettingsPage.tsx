import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

type AppSettings = {
  webwright?: {
    executionMode?: string
    [key: string]: unknown
  }
  [key: string]: unknown
}

export function SettingsPage() {
  const project = useAppStore((s) => s.currentProject)
  const [settingsText, setSettingsText] = useState('')
  const [health, setHealth] = useState('')
  const qc = useQueryClient()

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings.get })
  useEffect(() => {
    if (settings) setSettingsText(JSON.stringify(settings, null, 2))
  }, [settings])

  const saveMut = useMutation({
    mutationFn: () => api.settings.update(JSON.parse(settingsText)),
    onSuccess: (saved) => {
      setSettingsText(JSON.stringify(saved, null, 2))
      qc.invalidateQueries({ queryKey: ['settings'] })
    }
  })

  const parsedSettings = parseSettings(settingsText)
  const executionMode = parsedSettings?.webwright?.executionMode || 'native'

  function updateExecutionMode(mode: 'native' | 'wsl') {
    const next = parsedSettings || { ...(settings as AppSettings | undefined) }
    next.webwright = { ...(next.webwright || {}), executionMode: mode }
    setSettingsText(JSON.stringify(next, null, 2))
  }

  async function checkHealth() {
    if (project?.generated_project_path) {
      const res = await api.projectHealth(project.id, project.generated_project_path)
      setHealth(JSON.stringify(res, null, 2))
    } else {
      const res = await api.health()
      setHealth(JSON.stringify(res, null, 2))
    }
  }

  async function installDeps() {
    if (!project?.generated_project_path) return
    const res = await api.installDeps(project.id, project.generated_project_path)
    setHealth(JSON.stringify(res, null, 2))
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <h2 className="text-2xl font-bold">Settings</h2>
      <div className="rounded border border-slate-800 bg-slate-900 p-3">
        <label className="block text-sm font-medium mb-2">Webwright runtime</label>
        <div className="inline-flex overflow-hidden rounded border border-slate-700">
          {(['native', 'wsl'] as const).map((mode) => (
            <button
              key={mode}
              className={`px-4 py-2 text-sm ${executionMode === mode ? 'bg-blue-600 text-white' : 'bg-slate-950 text-slate-300 hover:bg-slate-800'}`}
              onClick={() => updateExecutionMode(mode)}
              type="button"
            >
              {mode === 'native' ? 'Native' : 'WSL'}
            </button>
          ))}
        </div>
      </div>
      <textarea className="w-full h-64 p-3 rounded bg-slate-900 font-mono text-sm" value={settingsText} onChange={(e) => setSettingsText(e.target.value)} />
      <div className="flex gap-2">
        <button className="px-4 py-2 bg-blue-600 rounded" onClick={() => saveMut.mutate()}>Save</button>
        <button className="px-4 py-2 bg-slate-700 rounded" onClick={checkHealth}>Health Check</button>
        <button className="px-4 py-2 bg-slate-700 rounded" onClick={installDeps}>Install Dependencies</button>
      </div>
      {health && <pre className="text-xs bg-slate-900 p-3 rounded overflow-auto">{health}</pre>}
      <p className="text-xs text-slate-500">API keys are stored in OS credential store via keytar, not in settings.json.</p>
    </div>
  )
}

function parseSettings(value: string): AppSettings | null {
  try {
    return JSON.parse(value) as AppSettings
  } catch {
    return null
  }
}
