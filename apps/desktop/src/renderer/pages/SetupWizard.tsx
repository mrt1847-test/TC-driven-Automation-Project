import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

const steps = [
  'Webwright Root',
  'Python venv',
  'API Provider',
  'API Key',
  'Playwright Browser',
  'Smoke Test',
  'Project Path'
]

export function SetupWizard() {
  const [step, setStep] = useState(0)
  const [webwrightRoot, setWebwrightRoot] = useState('')
  const [pythonPath, setPythonPath] = useState('python')
  const [apiKey, setApiKey] = useState('')
  const [projectRoot, setProjectRoot] = useState('')
  const [health, setHealth] = useState<string>('')
  const setSetupComplete = useAppStore((s) => s.setSetupComplete)
  const navigate = useNavigate()

  const saveSettings = useMutation({
    mutationFn: async () => {
      const current = await api.settings.get()
      const updated = {
        ...current,
        webwright: {
          ...(current.webwright as object),
          root: webwrightRoot,
          python: pythonPath,
          executionMode: 'native'
        },
        generator: {
          ...(current.generator as object),
          projectRoot
        }
      }
      await api.settings.update(updated)
      if (apiKey) {
        await window.electronAPI?.credentialSet('tc-studio', 'openai', apiKey)
      }
    }
  })

  async function checkHealth() {
    const res = await api.settings.validate()
    setHealth(JSON.stringify(res, null, 2))
  }

  async function pickDir(setter: (v: string) => void) {
    const path = await window.electronAPI?.selectDirectory()
    if (path) setter(path)
  }

  async function finish() {
    await saveSettings.mutateAsync()
    setSetupComplete(true)
    navigate('/')
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h2 className="text-2xl font-bold">Setup Wizard</h2>
      <p className="text-slate-400">Step {step + 1} / {steps.length}: {steps[step]}</p>

      {step === 0 && (
        <div className="space-y-2">
          <input className="w-full p-2 rounded bg-slate-800" value={webwrightRoot} onChange={(e) => setWebwrightRoot(e.target.value)} placeholder="Webwright root path" />
          <button className="px-4 py-2 bg-slate-700 rounded" onClick={() => pickDir(setWebwrightRoot)}>Browse</button>
        </div>
      )}
      {step === 1 && (
        <input className="w-full p-2 rounded bg-slate-800" value={pythonPath} onChange={(e) => setPythonPath(e.target.value)} placeholder="Python path" />
      )}
      {step === 2 && <p className="text-slate-300">OpenAI provider (default)</p>}
      {step === 3 && (
        <input className="w-full p-2 rounded bg-slate-800" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="API Key (stored in OS keychain)" />
      )}
      {step === 4 && (
        <div>
          <button className="px-4 py-2 bg-blue-600 rounded" onClick={checkHealth}>Check Webwright / Python</button>
          {health && <pre className="mt-2 text-xs bg-slate-900 p-2 rounded overflow-auto">{health}</pre>}
        </div>
      )}
      {step === 5 && (
        <div>
          <button className="px-4 py-2 bg-blue-600 rounded" onClick={checkHealth}>Run Smoke Test</button>
        </div>
      )}
      {step === 6 && (
        <div className="space-y-2">
          <input className="w-full p-2 rounded bg-slate-800" value={projectRoot} onChange={(e) => setProjectRoot(e.target.value)} placeholder="Default project root" />
          <button className="px-4 py-2 bg-slate-700 rounded" onClick={() => pickDir(setProjectRoot)}>Browse</button>
        </div>
      )}

      <div className="flex gap-2">
        {step > 0 && <button className="px-4 py-2 bg-slate-700 rounded" onClick={() => setStep(step - 1)}>Back</button>}
        {step < steps.length - 1 ? (
          <button className="px-4 py-2 bg-blue-600 rounded" onClick={() => setStep(step + 1)}>Next</button>
        ) : (
          <button className="px-4 py-2 bg-green-600 rounded" onClick={finish}>Finish</button>
        )}
      </div>
    </div>
  )
}
