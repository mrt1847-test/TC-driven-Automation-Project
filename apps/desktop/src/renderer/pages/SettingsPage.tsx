import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

type IntegrationConfig = {
  baseUrl?: string
  enabled?: boolean
}

type HealthCheck = {
  ok?: boolean
  message?: string
  path?: string
  browser?: string
}

type HealthResponse = Record<string, HealthCheck | boolean>

type AppSettings = {
  runtime?: {
    mode?: 'custom' | 'bundled'
    python?: string
    webwrightRoot?: string
    webwrightPython?: string
    playwrightBrowsersPath?: string
    templatePath?: string
    [key: string]: unknown
  }
  webwright?: {
    executionMode?: string
    root?: string
    python?: string
    baseConfig?: string
    modelConfig?: string
    outputRoot?: string
    apiProvider?: string
    [key: string]: unknown
  }
  generator?: {
    projectRoot?: string
    templatePath?: string
    defaultFramework?: string
    defaultLanguage?: string
    [key: string]: unknown
  }
  runner?: {
    defaultBrowser?: string
    defaultEnv?: string
    headless?: boolean
    [key: string]: unknown
  }
  integrations?: {
    testrailClone?: IntegrationConfig
    testrail?: IntegrationConfig
    googleSheets?: { enabled?: boolean }
    [key: string]: unknown
  }
  [key: string]: unknown
}

const inputClass = 'w-full p-2 rounded bg-slate-950 border border-slate-700 text-sm'
const sectionClass = 'rounded border border-slate-800 bg-slate-900 p-4 space-y-3'

export function SettingsPage() {
  const project = useAppStore((s) => s.currentProject)
  const openSetupWizardRerun = useAppStore((s) => s.openSetupWizardRerun)
  const [settingsText, setSettingsText] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [health, setHealth] = useState('')
  const [validation, setValidation] = useState<HealthResponse | null>(null)
  const qc = useQueryClient()

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings.get })
  useEffect(() => {
    if (settings) setSettingsText(JSON.stringify(settings, null, 2))
  }, [settings])

  const saveMut = useMutation({
    mutationFn: async () => {
      const body = JSON.parse(settingsText) as AppSettings
      const saved = await api.settings.update(body)
      const provider = (saved as AppSettings).webwright?.apiProvider || body.webwright?.apiProvider
      if (apiKey && provider) {
        await window.electronAPI?.credentialSet('tc-studio', provider, apiKey)
        setApiKey('')
      }
      return saved
    },
    onSuccess: (saved) => {
      setSettingsText(JSON.stringify(saved, null, 2))
      qc.invalidateQueries({ queryKey: ['settings'] })
    }
  })

  const validateMut = useMutation({
    mutationFn: async () => {
      const body = JSON.parse(settingsText) as AppSettings
      const saved = await api.settings.update(body)
      const provider = (saved as AppSettings).webwright?.apiProvider || body.webwright?.apiProvider
      if (apiKey && provider) {
        await window.electronAPI?.credentialSet('tc-studio', provider, apiKey)
        setApiKey('')
      }
      setSettingsText(JSON.stringify(saved, null, 2))
      return api.settings.validate() as Promise<HealthResponse>
    },
    onSuccess: (res) => {
      setValidation(res)
      setHealth(JSON.stringify(res, null, 2))
      qc.invalidateQueries({ queryKey: ['settings'] })
    }
  })

  const parsedSettings = parseSettings(settingsText)
  const runtime = parsedSettings?.runtime || {}
  const webwright = parsedSettings?.webwright || {}
  const generator = parsedSettings?.generator || {}
  const runner = parsedSettings?.runner || {}
  const integrations = parsedSettings?.integrations || {}
  const browserCheck = getHealthCheck(validation, 'playwrightBrowser')
  const smokeTestRan = typeof validation?.allOk === 'boolean'
  const smokeTestPassed = validation?.allOk === true

  function applyPatch(patch: (draft: AppSettings) => void) {
    setSettingsText((current) => patchSettings(current, settings as AppSettings | undefined, patch))
  }

  function updateExecutionMode(mode: 'native' | 'wsl') {
    applyPatch((draft) => {
      draft.webwright = { ...(draft.webwright || {}), executionMode: mode }
    })
  }

  async function pickDirectory(field: 'webwright.root' | 'webwright.python' | 'webwright.outputRoot' | 'generator.projectRoot' | 'generator.templatePath') {
    const path = await window.electronAPI?.selectDirectory()
    if (!path) return

    applyPatch((draft) => {
      if (field === 'generator.projectRoot') {
        draft.generator = { ...(draft.generator || {}), projectRoot: path }
      } else if (field === 'generator.templatePath') {
        draft.generator = { ...(draft.generator || {}), templatePath: path }
      } else if (field === 'webwright.root') {
        draft.webwright = { ...(draft.webwright || {}), root: path }
      } else if (field === 'webwright.python') {
        draft.webwright = { ...(draft.webwright || {}), python: path }
      } else {
        draft.webwright = { ...(draft.webwright || {}), outputRoot: path }
      }
    })
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

      <section className={sectionClass}>
        <h3 className="text-sm font-medium">Setup Wizard parity</h3>
        {runtime.mode === 'bundled' && <p className="text-xs text-amber-400">Bundled mode: Webwright/Python paths are installer-managed.</p>}
        <p className="text-xs text-slate-500">Re-edit the same fields configured during first-run setup.</p>
        <label className="block text-xs text-slate-400">
          Webwright root
          <div className="mt-1 flex gap-2">
            <input
              disabled={runtime.mode === 'bundled'}
              className={`${inputClass} ${runtime.mode === 'bundled' ? 'opacity-60' : ''}`}
              value={webwright.root || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.webwright = { ...(draft.webwright || {}), root: e.target.value }
              })}
              placeholder="Webwright root path"
            />
            <button disabled={runtime.mode === 'bundled'} className="px-3 py-2 bg-slate-700 rounded text-sm shrink-0 disabled:opacity-60" type="button" onClick={() => pickDirectory('webwright.root')}>
              Browse
            </button>
          </div>
        </label>
        <label className="block text-xs text-slate-400">
          Python / venv
          <div className="mt-1 flex gap-2">
            <input
              disabled={runtime.mode === 'bundled'}
              className={`${inputClass} ${runtime.mode === 'bundled' ? 'opacity-60' : ''}`}
              value={webwright.python || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.webwright = { ...(draft.webwright || {}), python: e.target.value }
              })}
              placeholder="Python path or venv interpreter"
            />
            <button disabled={runtime.mode === 'bundled'} className="px-3 py-2 bg-slate-700 rounded text-sm shrink-0 disabled:opacity-60" type="button" onClick={() => pickDirectory('webwright.python')}>
              Browse venv
            </button>
          </div>
        </label>
        <label className="block text-xs text-slate-400">
          API provider
          <select
            className={`${inputClass} mt-1`}
            value={webwright.apiProvider || 'openai'}
            onChange={(e) => applyPatch((draft) => {
              draft.webwright = { ...(draft.webwright || {}), apiProvider: e.target.value }
            })}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="azure-openai">Azure OpenAI</option>
          </select>
        </label>
        <label className="block text-xs text-slate-400">
          API key
          <input
            className={`${inputClass} mt-1`}
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Enter to update OS keychain secret (never stored in settings.json)"
          />
        </label>
      </section>

      <section className={sectionClass}>
        <h3 className="text-sm font-medium">Setup Wizard re-run</h3>
        <p className="text-xs text-slate-500">Optional full wizard flow from Settings. Main app access stays enabled (`setupComplete` is not reset).</p>
        <button className="px-4 py-2 bg-slate-700 rounded" type="button" onClick={() => openSetupWizardRerun()}>
          Re-run Setup Wizard
        </button>
      </section>

      <section className={sectionClass}>
        <h3 className="text-sm font-medium">Webwright runtime</h3>
        <div className="inline-flex overflow-hidden rounded border border-slate-700">
          {(['native', 'wsl'] as const).map((mode) => (
            <button
              key={mode}
              className={`px-4 py-2 text-sm ${(webwright.executionMode || 'native') === mode ? 'bg-blue-600 text-white' : 'bg-slate-950 text-slate-300 hover:bg-slate-800'}`}
              onClick={() => updateExecutionMode(mode)}
              type="button"
            >
              {mode === 'native' ? 'Native' : 'WSL'}
            </button>
          ))}
        </div>
      </section>

      <section className={sectionClass}>
        <h3 className="text-sm font-medium">Webwright &amp; LLM</h3>
        <label className="block text-xs text-slate-400">
          Base config file
          <input
            className={`${inputClass} mt-1`}
            value={webwright.baseConfig || ''}
            onChange={(e) => applyPatch((draft) => {
              draft.webwright = { ...(draft.webwright || {}), baseConfig: e.target.value }
            })}
            placeholder="base.yaml"
          />
        </label>
        <label className="block text-xs text-slate-400">
          Model config file
          <input
            className={`${inputClass} mt-1`}
            value={webwright.modelConfig || ''}
            onChange={(e) => applyPatch((draft) => {
              draft.webwright = { ...(draft.webwright || {}), modelConfig: e.target.value }
            })}
            placeholder="model_openai.yaml"
          />
        </label>
        <label className="block text-xs text-slate-400">
          Output root
          <div className="mt-1 flex gap-2">
            <input
              disabled={runtime.mode === 'bundled'}
              className={`${inputClass} ${runtime.mode === 'bundled' ? 'opacity-60' : ''}`}
              value={webwright.outputRoot || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.webwright = { ...(draft.webwright || {}), outputRoot: e.target.value }
              })}
              placeholder="Webwright run output directory"
            />
            <button className="px-3 py-2 bg-slate-700 rounded text-sm shrink-0" type="button" onClick={() => pickDirectory('webwright.outputRoot')}>
              Browse
            </button>
          </div>
        </label>
      </section>

      <section className={sectionClass}>
        <h3 className="text-sm font-medium">Generator</h3>
        <label className="block text-xs text-slate-400">
          Default project root
          <div className="mt-1 flex gap-2">
            <input
              disabled={runtime.mode === 'bundled'}
              className={`${inputClass} ${runtime.mode === 'bundled' ? 'opacity-60' : ''}`}
              value={generator.projectRoot || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.generator = { ...(draft.generator || {}), projectRoot: e.target.value }
              })}
              placeholder="Default automation project root"
            />
            <button className="px-3 py-2 bg-slate-700 rounded text-sm shrink-0" type="button" onClick={() => pickDirectory('generator.projectRoot')}>
              Browse
            </button>
          </div>
        </label>
        <label className="block text-xs text-slate-400">
          Template path
          <div className="mt-1 flex gap-2">
            <input
              disabled={runtime.mode === 'bundled'}
              className={`${inputClass} ${runtime.mode === 'bundled' ? 'opacity-60' : ''}`}
              value={generator.templatePath || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.generator = { ...(draft.generator || {}), templatePath: e.target.value }
              })}
              placeholder="Generated project template directory"
            />
            <button className="px-3 py-2 bg-slate-700 rounded text-sm shrink-0" type="button" onClick={() => pickDirectory('generator.templatePath')}>
              Browse
            </button>
          </div>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs text-slate-400">
            Default framework
            <input
              className={`${inputClass} mt-1`}
              value={generator.defaultFramework || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.generator = { ...(draft.generator || {}), defaultFramework: e.target.value }
              })}
              placeholder="playwright-pytest"
            />
          </label>
          <label className="block text-xs text-slate-400">
            Default language
            <input
              className={`${inputClass} mt-1`}
              value={generator.defaultLanguage || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.generator = { ...(draft.generator || {}), defaultLanguage: e.target.value }
              })}
              placeholder="python"
            />
          </label>
        </div>
      </section>

      <section className={sectionClass}>
        <h3 className="text-sm font-medium">Runner defaults</h3>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs text-slate-400">
            Default browser
            <select
              className={`${inputClass} mt-1`}
              value={runner.defaultBrowser || 'chromium'}
              onChange={(e) => applyPatch((draft) => {
                draft.runner = { ...(draft.runner || {}), defaultBrowser: e.target.value }
              })}
            >
              <option value="chromium">Chromium</option>
              <option value="firefox">Firefox</option>
              <option value="webkit">WebKit</option>
            </select>
          </label>
          <label className="block text-xs text-slate-400">
            Default environment
            <input
              className={`${inputClass} mt-1`}
              value={runner.defaultEnv || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.runner = { ...(draft.runner || {}), defaultEnv: e.target.value }
              })}
              placeholder="stg"
            />
          </label>
        </div>
        <label className="inline-flex items-center gap-2 text-sm text-slate-300">
          <input
            checked={runner.headless !== false}
            type="checkbox"
            onChange={(e) => applyPatch((draft) => {
              draft.runner = { ...(draft.runner || {}), headless: e.target.checked }
            })}
          />
          Run headless by default
        </label>
      </section>

      <section className={sectionClass}>
        <h3 className="text-sm font-medium">Integrations</h3>
        <IntegrationRow
          enabled={integrations.testrailClone?.enabled === true}
          label="testrail-clone"
          baseUrl={integrations.testrailClone?.baseUrl || ''}
          onChange={(next) => applyPatch((draft) => {
            draft.integrations = {
              ...(draft.integrations || {}),
              testrailClone: next
            }
          })}
        />
        <IntegrationRow
          enabled={integrations.testrail?.enabled === true}
          label="TestRail"
          baseUrl={integrations.testrail?.baseUrl || ''}
          onChange={(next) => applyPatch((draft) => {
            draft.integrations = {
              ...(draft.integrations || {}),
              testrail: next
            }
          })}
        />
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            checked={integrations.googleSheets?.enabled === true}
            type="checkbox"
            onChange={(e) => applyPatch((draft) => {
              draft.integrations = {
                ...(draft.integrations || {}),
                googleSheets: { enabled: e.target.checked }
              }
            })}
          />
          Google Sheets export enabled
        </label>
      </section>

      <section className={sectionClass}>
        <h3 className="text-sm font-medium">Advanced JSON</h3>
        <textarea
          className="w-full h-48 p-3 rounded bg-slate-950 border border-slate-700 font-mono text-sm"
          value={settingsText}
          onChange={(e) => setSettingsText(e.target.value)}
        />
      </section>

      <div className="flex flex-wrap gap-2">
        <button className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50" disabled={saveMut.isPending || !parsedSettings} onClick={() => saveMut.mutate()}>
          {saveMut.isPending ? 'Saving...' : 'Save'}
        </button>
        <button className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50" disabled={validateMut.isPending || !parsedSettings} onClick={() => validateMut.mutate()}>
          {validateMut.isPending ? 'Validating...' : 'Validate Settings'}
        </button>
        <button className="px-4 py-2 bg-slate-700 rounded" onClick={checkHealth}>Health Check</button>
        <button className="px-4 py-2 bg-slate-700 rounded" onClick={installDeps}>Install Dependencies</button>
      </div>
      {validation && (
        <div className="space-y-3">
          {browserCheck && (
            <div className={`rounded border p-3 text-sm ${browserCheck.ok ? 'border-green-700 bg-green-950/30' : 'border-yellow-700 bg-yellow-950/30'}`}>
              <div className="font-medium">{browserCheck.ok ? 'Browser ready' : 'Browser needs attention'}</div>
              {(browserCheck.path || browserCheck.message) && (
                <div className="mt-1 break-all text-xs text-slate-400">{browserCheck.path || browserCheck.message}</div>
              )}
            </div>
          )}
          {smokeTestRan && (
            <div className={`rounded border p-3 text-sm ${smokeTestPassed ? 'border-green-700 bg-green-950/30' : 'border-red-700 bg-red-950/30'}`}>
              <div className="font-medium">{smokeTestPassed ? 'Smoke test passed' : 'Smoke test failed'}</div>
              <div className="mt-1 text-xs text-slate-400">
                {smokeTestPassed
                  ? 'Worker, settings, Python, Webwright, template, and Playwright checks are ready.'
                  : 'Review the failed checks below before continuing.'}
              </div>
            </div>
          )}
        </div>
      )}
      {health && <pre className="text-xs bg-slate-900 p-3 rounded overflow-auto">{health}</pre>}
      <p className="text-xs text-slate-500">API keys are stored in OS credential store via keytar, not in settings.json.</p>
    </div>
  )
}

function IntegrationRow({
  label,
  enabled,
  baseUrl,
  onChange
}: {
  label: string
  enabled: boolean
  baseUrl: string
  onChange: (next: IntegrationConfig) => void
}) {
  return (
    <div className="rounded border border-slate-800 p-3 space-y-2">
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          checked={enabled}
          type="checkbox"
          onChange={(e) => onChange({ baseUrl, enabled: e.target.checked })}
        />
        {label} enabled
      </label>
      <input
        className={inputClass}
        value={baseUrl}
        onChange={(e) => onChange({ enabled, baseUrl: e.target.value })}
        placeholder="Base URL"
      />
    </div>
  )
}

function getHealthCheck(health: HealthResponse | null, key: string): HealthCheck | null {
  const value = health?.[key]
  return typeof value === 'object' && value !== null ? value : null
}

function patchSettings(
  settingsText: string,
  fallback: AppSettings | undefined,
  patch: (draft: AppSettings) => void
): string {
  const base = parseSettings(settingsText) || fallback || {}
  const draft = JSON.parse(JSON.stringify(base)) as AppSettings
  patch(draft)
  return JSON.stringify(draft, null, 2)
}

function parseSettings(value: string): AppSettings | null {
  try {
    return JSON.parse(value) as AppSettings
  } catch {
    return null
  }
}


