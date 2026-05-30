import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

const steps = [
  'Webwright Root',
  'Python',
  'API Provider / Key',
  'Playwright Browser',
  'Smoke Test',
  'Project Path',
  'Complete'
]

export function SetupWizard() {
  const [step, setStep] = useState(0)
  const [webwrightRoot, setWebwrightRoot] = useState('')
  const [pythonPath, setPythonPath] = useState('python')
  const [apiProvider, setApiProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const [projectRoot, setProjectRoot] = useState('')
  const [health, setHealth] = useState<string>('')
  const setSetupComplete = useAppStore((s) => s.setSetupComplete)

  const saveSettings = useMutation({
    mutationFn: saveDraftSettings
  })

  async function checkHealth() {
    await saveSettings.mutateAsync()
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
  }

  async function saveDraftSettings() {
    const current = await api.settings.get()
    const updated = {
      ...current,
      webwright: {
        ...(current.webwright as object),
        root: webwrightRoot,
        python: pythonPath,
        apiProvider,
        executionMode: 'native'
      },
      generator: {
        ...(current.generator as object),
        projectRoot
      }
    }
    await api.settings.update(updated)
    if (apiKey) {
      await window.electronAPI?.credentialSet('tc-studio', apiProvider, apiKey)
    }
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
        <div className="space-y-2">
          <input className="w-full p-2 rounded bg-slate-800" value={pythonPath} onChange={(e) => setPythonPath(e.target.value)} placeholder="Python path or venv interpreter" />
          <button className="px-4 py-2 bg-slate-700 rounded" onClick={() => pickDir(setPythonPath)}>Browse venv</button>
        </div>
      )}
      {step === 2 && (
        <div className="space-y-2">
          <select className="w-full p-2 rounded bg-slate-800" value={apiProvider} onChange={(e) => setApiProvider(e.target.value)}>
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="azure-openai">Azure OpenAI</option>
          </select>
          <input className="w-full p-2 rounded bg-slate-800" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="API Key (stored in OS keychain)" />
        </div>
      )}
      {step === 3 && (
        <div>
          <button className="px-4 py-2 bg-blue-600 rounded" onClick={checkHealth}>Check Webwright / Python</button>
          {health && <pre className="mt-2 text-xs bg-slate-900 p-2 rounded overflow-auto">{health}</pre>}
        </div>
      )}
      {step === 4 && (
        <div>
          <button className="px-4 py-2 bg-blue-600 rounded" onClick={checkHealth}>Run Smoke Test</button>
          {health && <pre className="mt-2 text-xs bg-slate-900 p-2 rounded overflow-auto">{health}</pre>}
        </div>
      )}
      {step === 5 && (
        <div className="space-y-2">
          <input className="w-full p-2 rounded bg-slate-800" value={projectRoot} onChange={(e) => setProjectRoot(e.target.value)} placeholder="Default project root" />
          <button className="px-4 py-2 bg-slate-700 rounded" onClick={() => pickDir(setProjectRoot)}>Browse</button>
        </div>
      )}
      {step === 6 && (
        <div className="space-y-3 text-slate-300">
          <p>Setup is ready to finish.</p>
          {health && <pre className="text-xs bg-slate-900 p-2 rounded overflow-auto">{health}</pre>}
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
