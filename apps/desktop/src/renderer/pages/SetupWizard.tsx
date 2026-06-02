import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

type HealthCheck = {
  ok?: boolean
  message?: string
  path?: string
  browser?: string
}

type HealthResponse = Record<string, HealthCheck | boolean>

type SetupWizardProps = {
  mode?: 'first-run' | 'rerun'
}

const steps = [
  'Webwright Root',
  'Python',
  'API Provider / Key',
  'Playwright Browser',
  'Smoke Test',
  'Project Path',
  'Complete'
]

export function SetupWizard({ mode = 'first-run' }: SetupWizardProps) {
  const [step, setStep] = useState(0)
  const [webwrightRoot, setWebwrightRoot] = useState('')
  const [pythonPath, setPythonPath] = useState('python')
  const [apiProvider, setApiProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const [projectRoot, setProjectRoot] = useState('')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [runtimeMode, setRuntimeMode] = useState<'custom' | 'bundled'>('custom')
  const setSetupComplete = useAppStore((s) => s.setSetupComplete)
  const closeSetupWizardRerun = useAppStore((s) => s.closeSetupWizardRerun)

  const saveSettings = useMutation({
    mutationFn: saveDraftSettings
  })

  useEffect(() => {
    api.settings.get().then((current) => {
      const webwright = current.webwright as Record<string, string> | undefined
      const generator = current.generator as Record<string, string> | undefined
      if (webwright?.root) setWebwrightRoot(webwright.root)
      if (webwright?.python) setPythonPath(webwright.python)
      if (webwright?.apiProvider) setApiProvider(webwright.apiProvider)
      if (generator?.projectRoot) setProjectRoot(generator.projectRoot)
      const runtime = current.runtime as Record<string, string> | undefined
      if (runtime?.mode === 'bundled') {
        setRuntimeMode('bundled')
        if (runtime.python) setPythonPath(runtime.python)
        if (runtime.webwrightRoot) setWebwrightRoot(runtime.webwrightRoot)
      }
    })
  }, [])

  async function checkHealth() {
    await saveSettings.mutateAsync()
    const res = await api.settings.validate() as HealthResponse
    setHealth(res)
  }

  async function pickDir(setter: (v: string) => void) {
    const path = await window.electronAPI?.selectDirectory()
    if (path) setter(path)
  }

  async function finish() {
    await saveSettings.mutateAsync()
    if (mode === 'rerun') {
      closeSetupWizardRerun()
      return
    }
    setSetupComplete(true)
  }

  function cancelRerun() {
    closeSetupWizardRerun()
  }

  async function nextStep() {
    if (step === 0 || step === 1 || step === 2 || step === 5) {
      await saveSettings.mutateAsync()
    }
    setStep(step + 1)
  }

  async function saveDraftSettings() {
    const current = await api.settings.get()
    const webwright = current.webwright as Record<string, unknown> | undefined
    const updated = {
      ...current,
      runtime: {
        ...(current.runtime as object),
        mode: runtimeMode,
        python: pythonPath,
        webwrightRoot: webwrightRoot
      },
      webwright: {
        ...(current.webwright as object),
        root: webwrightRoot,
        python: pythonPath,
        apiProvider,
        executionMode: webwright?.executionMode || 'native'
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

  function getHealthCheck(key: string): HealthCheck | null {
    const value = health?.[key]
    return typeof value === 'object' && value !== null ? value : null
  }

  const browserCheck = getHealthCheck('playwrightBrowser')
  const smokeTestRan = typeof health?.allOk === 'boolean'
  const smokeTestPassed = health?.allOk === true

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h2 className="text-2xl font-bold">Setup Wizard</h2>
      {mode === 'rerun' && (
        <p className="text-sm text-slate-400">Re-running setup from Settings. Your main app access stays enabled.</p>
      )}
      <p className="text-slate-400">Step {step + 1} / {steps.length}: {steps[step]}</p>

      {step === 0 && (
        <div className="space-y-2">
          {runtimeMode === 'bundled' ? (
            <p className="text-xs text-slate-400">Bundled runtime mode: Webwright root is managed by installer resources.</p>
          ) : null}
        <div className="space-y-2">
          <input disabled={runtimeMode === 'bundled'} className="w-full p-2 rounded bg-slate-800 disabled:opacity-60" value={webwrightRoot} onChange={(e) => setWebwrightRoot(e.target.value)} placeholder="Webwright root path" />
          <button disabled={runtimeMode === 'bundled'} className="px-4 py-2 bg-slate-700 rounded disabled:opacity-60" onClick={() => pickDir(setWebwrightRoot)}>Browse</button>
        </div>
        </div>
      )}
      {step === 1 && (
        <div className="space-y-2">
          <input disabled={runtimeMode === 'bundled'} className="w-full p-2 rounded bg-slate-800 disabled:opacity-60" value={pythonPath} onChange={(e) => setPythonPath(e.target.value)} placeholder="Python path or venv interpreter" />
          <button disabled={runtimeMode === 'bundled'} className="px-4 py-2 bg-slate-700 rounded disabled:opacity-60" onClick={() => pickDir(setPythonPath)}>Browse venv</button>
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
        <div className="space-y-3">
          <button className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50" disabled={saveSettings.isPending} onClick={checkHealth}>
            {saveSettings.isPending ? 'Checking...' : 'Check Playwright Browser'}
          </button>
          {browserCheck && (
            <div className={`rounded border p-3 text-sm ${browserCheck.ok ? 'border-green-700 bg-green-950/30' : 'border-yellow-700 bg-yellow-950/30'}`}>
              <div className="font-medium">{browserCheck.ok ? 'Browser ready' : 'Browser needs attention'}</div>
              <div className="mt-1 text-xs text-slate-300">{browserCheck.browser || 'chromium'}</div>
              {(browserCheck.path || browserCheck.message) && (
                <div className="mt-1 break-all text-xs text-slate-400">{browserCheck.path || browserCheck.message}</div>
              )}
            </div>
          )}
          {health && <pre className="mt-2 text-xs bg-slate-900 p-2 rounded overflow-auto">{JSON.stringify(health, null, 2)}</pre>}
        </div>
      )}
      {step === 4 && (
        <div className="space-y-3">
          <button className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50" disabled={saveSettings.isPending} onClick={checkHealth}>
            {saveSettings.isPending ? 'Running...' : 'Run Smoke Test'}
          </button>
          {smokeTestRan && (
            <div className={`rounded border p-3 text-sm ${smokeTestPassed ? 'border-green-700 bg-green-950/30' : 'border-red-700 bg-red-950/30'}`}>
              <div className="font-medium">{smokeTestPassed ? 'Smoke test passed' : 'Smoke test failed'}</div>
              <div className="mt-1 text-xs text-slate-400">
                {smokeTestPassed
                  ? 'Worker, settings, Python, Webwright, template, and Playwright checks are ready.'
                  : 'Review the failed checks below before finishing setup.'}
              </div>
            </div>
          )}
          {health && <pre className="mt-2 text-xs bg-slate-900 p-2 rounded overflow-auto">{JSON.stringify(health, null, 2)}</pre>}
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
          {health && <pre className="text-xs bg-slate-900 p-2 rounded overflow-auto">{JSON.stringify(health, null, 2)}</pre>}
        </div>
      )}

      <div className="flex gap-2">
        {mode === 'rerun' && (
          <button className="px-4 py-2 bg-slate-700 rounded" onClick={cancelRerun}>Cancel</button>
        )}
        {step > 0 && <button className="px-4 py-2 bg-slate-700 rounded" onClick={() => setStep(step - 1)}>Back</button>}
        {step < steps.length - 1 ? (
          <button className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50" disabled={saveSettings.isPending} onClick={nextStep}>
            {saveSettings.isPending ? 'Saving...' : 'Next'}
          </button>
        ) : (
          <button className="px-4 py-2 bg-green-600 rounded disabled:opacity-50" disabled={saveSettings.isPending} onClick={finish}>
            {saveSettings.isPending ? 'Saving...' : 'Finish'}
          </button>
        )}
      </div>
    </div>
  )
}


