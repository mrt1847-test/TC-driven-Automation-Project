import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

export function SettingsPage() {
  const project = useAppStore((s) => s.currentProject)
  const [settingsText, setSettingsText] = useState('')
  const [health, setHealth] = useState('')

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings.get })
  useEffect(() => {
    if (settings) setSettingsText(JSON.stringify(settings, null, 2))
  }, [settings])

  const saveMut = useMutation({
    mutationFn: () => api.settings.update(JSON.parse(settingsText))
  })

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
