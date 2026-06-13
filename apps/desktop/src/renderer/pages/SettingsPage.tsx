import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type ConnectorCredentialsResponse } from '@/lib/api'
import { useAppStore } from '@/store/appStore'

type IntegrationConfig = {
  baseUrl?: string
  enabled?: boolean
  username?: string
  spreadsheetId?: string
  serviceAccountEmail?: string
  [key: string]: unknown
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
    modelName?: string
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
    googleSheets?: IntegrationConfig
    [key: string]: unknown
  }
  self_healing?: {
    autoApplyProjectIds?: unknown
    auto_apply_project_ids?: unknown
    [key: string]: unknown
  }
  [key: string]: unknown
}

const DEFAULT_CREDENTIAL_SERVICE = 'tc-studio'
const DEFAULT_CONNECTOR_ACCOUNTS = {
  testrail: { apiToken: 'connector:testrail:apiToken' },
  googleSheets: { serviceAccountJson: 'connector:googleSheets:serviceAccountJson' }
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
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [modelStatus, setModelStatus] = useState('Load available models to verify access for the selected provider key.')
  const [testRailApiToken, setTestRailApiToken] = useState('')
  const [googleSheetsCredential, setGoogleSheetsCredential] = useState('')
  const [connectorCredentialPresence, setConnectorCredentialPresence] = useState<Record<string, boolean>>({})
  const qc = useQueryClient()

  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.settings.get })
  const { data: connectorCredentials } = useQuery({
    queryKey: ['settings', 'connector-credentials'],
    queryFn: api.settings.connectorCredentials
  })
  useEffect(() => {
    if (settings) setSettingsText(JSON.stringify(settings, null, 2))
  }, [settings])
  useEffect(() => {
    let cancelled = false

    async function refreshPresence() {
      if (!connectorCredentials || !window.electronAPI?.credentialGet) {
        setConnectorCredentialPresence({})
        return
      }
      const entries = Object.values(connectorCredentials.connectors).flatMap((connector) => connector.credentials)
      const next: Record<string, boolean> = {}
      await Promise.all(entries.map(async (credential) => {
        const result = await window.electronAPI.credentialGet(connectorCredentials.service, credential.account)
        next[credential.account] = result?.ok === true && result.hasCredential === true
      }))
      if (!cancelled) setConnectorCredentialPresence(next)
    }

    refreshPresence()
    return () => {
      cancelled = true
    }
  }, [connectorCredentials])

  const saveMut = useMutation({
    mutationFn: async () => {
      const body = JSON.parse(settingsText) as AppSettings
      const saved = await api.settings.update(body) as AppSettings
      await saveProviderCredential(saved, body)
      await saveConnectorCredentials()
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
      const saved = await api.settings.update(body) as AppSettings
      await saveProviderCredential(saved, body)
      await saveConnectorCredentials()
      setSettingsText(JSON.stringify(saved, null, 2))
      return api.settings.validate() as Promise<HealthResponse>
    },
    onSuccess: (res) => {
      setValidation(res)
      setHealth(JSON.stringify(res, null, 2))
      qc.invalidateQueries({ queryKey: ['settings'] })
    }
  })

  const loadModelsMut = useMutation({
    mutationFn: async () => {
      const body = JSON.parse(settingsText) as AppSettings
      const provider = body.webwright?.apiProvider || 'openai'
      if (apiKey) {
        const stored = await window.electronAPI?.credentialSet(DEFAULT_CREDENTIAL_SERVICE, provider, apiKey)
        if (!stored?.ok) {
          throw new Error(stored?.message || 'Could not store the API key before loading models.')
        }
        setApiKey('')
      }
      const result = await window.electronAPI?.providerModels(provider)
      if (!result) throw new Error('Model discovery is available in the desktop app only.')
      if (!result.ok) throw new Error(result.message)
      return result.models
    },
    onSuccess: (models) => {
      setAvailableModels(models)
      setModelStatus(`${models.length} compatible model(s) available for the stored key.`)
    },
    onError: (error) => {
      setAvailableModels([])
      setModelStatus(error instanceof Error ? error.message : 'Could not load provider models.')
    }
  })

  const parsedSettings = parseSettings(settingsText)
  const runtime = parsedSettings?.runtime || {}
  const webwright = parsedSettings?.webwright || {}
  const generator = parsedSettings?.generator || {}
  const runner = parsedSettings?.runner || {}
  const integrations = parsedSettings?.integrations || {}
  const selfHealing = parsedSettings?.self_healing || {}
  const autoApplyProjectIds = getAutoApplyProjectIds(selfHealing)
  const currentProjectAutoApplyEnabled = Boolean(project?.id && autoApplyProjectIds.includes(project.id))
  const browserCheck = getHealthCheck(validation, 'playwrightBrowser')
  const smokeTestRan = typeof validation?.allOk === 'boolean'
  const smokeTestPassed = validation?.allOk === true
  const credentialService = connectorCredentials?.service || DEFAULT_CREDENTIAL_SERVICE
  const testRailApiTokenAccount = getConnectorCredentialAccount(connectorCredentials, 'testrail', 'apiToken')
  const googleSheetsCredentialAccount = getConnectorCredentialAccount(
    connectorCredentials,
    'googleSheets',
    'serviceAccountJson'
  )

  function applyPatch(patch: (draft: AppSettings) => void) {
    setSettingsText((current) => patchSettings(current, settings as AppSettings | undefined, patch))
  }

  async function saveProviderCredential(saved: AppSettings, body: AppSettings) {
    const provider = saved.webwright?.apiProvider || body.webwright?.apiProvider
    if (!apiKey || !provider) return
    const stored = await window.electronAPI?.credentialSet(DEFAULT_CREDENTIAL_SERVICE, provider, apiKey)
    if (!stored?.ok) {
      throw new Error(stored?.message || 'Could not store the API key.')
    }
    setApiKey('')
  }

  async function saveConnectorCredentials(): Promise<string[]> {
    const storedAccounts: string[] = []
    if (testRailApiToken.trim()) {
      await storeCredentialDraft(credentialService, testRailApiTokenAccount, testRailApiToken, 'TestRail API token')
      storedAccounts.push(testRailApiTokenAccount)
      setTestRailApiToken('')
    }
    if (googleSheetsCredential.trim()) {
      await storeCredentialDraft(
        credentialService,
        googleSheetsCredentialAccount,
        googleSheetsCredential,
        'Google Sheets service account JSON'
      )
      storedAccounts.push(googleSheetsCredentialAccount)
      setGoogleSheetsCredential('')
    }
    if (storedAccounts.length) {
      setConnectorCredentialPresence((current) => ({
        ...current,
        ...Object.fromEntries(storedAccounts.map((account) => [account, true]))
      }))
    }
    return storedAccounts
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

  function updateCurrentProjectAutoApply(enabled: boolean) {
    if (!project) return
    applyPatch((draft) => {
      const current = draft.self_healing || {}
      const existingProjectIds = getAutoApplyProjectIds(current)
      const nextProjectIds = enabled
        ? Array.from(new Set([...existingProjectIds, project.id]))
        : existingProjectIds.filter((projectId) => projectId !== project.id)
      draft.self_healing = {
        ...current,
        autoApplyProjectIds: nextProjectIds
      }
      delete draft.self_healing.auto_apply_project_ids
    })
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
            onChange={(e) => {
              applyPatch((draft) => {
                draft.webwright = {
                  ...(draft.webwright || {}),
                  apiProvider: e.target.value,
                  modelName: ''
                }
              })
              setAvailableModels([])
              setModelStatus('Load available models to verify access for the selected provider key.')
            }}
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
          Model name override
          <div className="mt-1 flex gap-2">
            <input
              className={inputClass}
              list="webwright-model-options"
              value={webwright.modelName || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.webwright = { ...(draft.webwright || {}), modelName: e.target.value }
              })}
              placeholder="Use model config default"
            />
            <datalist id="webwright-model-options">
              {availableModels.map((model) => <option key={model} value={model} />)}
            </datalist>
            <button
              className="px-3 py-2 bg-slate-700 rounded text-sm shrink-0 disabled:opacity-50"
              disabled={loadModelsMut.isPending}
              type="button"
              onClick={() => loadModelsMut.mutate()}
            >
              {loadModelsMut.isPending ? 'Loading...' : 'Load models'}
            </button>
          </div>
          <span className={`mt-1 block text-xs ${
            availableModels.length && webwright.modelName && !availableModels.includes(webwright.modelName)
              ? 'text-amber-400'
              : 'text-slate-500'
          }`}>
            {availableModels.length && webwright.modelName && !availableModels.includes(webwright.modelName)
              ? `${webwright.modelName} is not available for the stored key. Select one of the ${availableModels.length} available models.`
              : modelStatus}
          </span>
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
        <h3 className="text-sm font-medium">Self-healing</h3>
        <label className={`flex items-start gap-3 rounded border border-slate-800 bg-slate-950 p-3 text-sm ${project ? 'text-slate-300' : 'text-slate-500'}`}>
          <input
            checked={currentProjectAutoApplyEnabled}
            className="mt-1"
            disabled={!project}
            type="checkbox"
            onChange={(e) => updateCurrentProjectAutoApply(e.target.checked)}
          />
          <span>
            <span className="block text-slate-200">Auto-apply safe selector healing for current project</span>
            <span className="mt-1 block text-xs text-slate-500">
              {project ? `${project.name} (${project.id})` : 'Select a project first.'}
            </span>
          </span>
        </label>
        <div className="text-xs text-slate-500">
          Enabled project IDs: {autoApplyProjectIds.length ? autoApplyProjectIds.join(', ') : 'None'}
        </div>
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
              testrail: { ...(draft.integrations?.testrail || {}), ...next }
            }
          })}
        >
          <label className="block text-xs text-slate-400">
            Username
            <input
              className={`${inputClass} mt-1`}
              value={integrations.testrail?.username || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.integrations = {
                  ...(draft.integrations || {}),
                  testrail: {
                    ...(draft.integrations?.testrail || {}),
                    enabled: integrations.testrail?.enabled === true,
                    baseUrl: integrations.testrail?.baseUrl || '',
                    username: e.target.value
                  }
                }
              })}
              placeholder="TestRail username or email"
            />
          </label>
          <label className="block text-xs text-slate-400">
            API token
            <input
              className={`${inputClass} mt-1`}
              type="password"
              value={testRailApiToken}
              onChange={(e) => setTestRailApiToken(e.target.value)}
              placeholder={connectorCredentialPresence[testRailApiTokenAccount] ? 'Stored. Enter to replace.' : 'Enter token to store securely'}
            />
            <span className="mt-1 block text-xs text-slate-500">
              {credentialStatusText(testRailApiTokenAccount, connectorCredentialPresence, testRailApiToken)}
            </span>
          </label>
        </IntegrationRow>
        <div className="rounded border border-slate-800 p-3 space-y-2">
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              checked={integrations.googleSheets?.enabled === true}
              type="checkbox"
              onChange={(e) => applyPatch((draft) => {
                draft.integrations = {
                  ...(draft.integrations || {}),
                  googleSheets: {
                    ...(draft.integrations?.googleSheets || {}),
                    enabled: e.target.checked
                  }
                }
              })}
            />
            Google Sheets export enabled
          </label>
          <label className="block text-xs text-slate-400">
            Default spreadsheet ID
            <input
              className={`${inputClass} mt-1`}
              value={integrations.googleSheets?.spreadsheetId || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.integrations = {
                  ...(draft.integrations || {}),
                  googleSheets: {
                    ...(draft.integrations?.googleSheets || {}),
                    enabled: integrations.googleSheets?.enabled === true,
                    spreadsheetId: e.target.value
                  }
                }
              })}
              placeholder="Spreadsheet ID"
            />
          </label>
          <label className="block text-xs text-slate-400">
            Service account email
            <input
              className={`${inputClass} mt-1`}
              value={integrations.googleSheets?.serviceAccountEmail || ''}
              onChange={(e) => applyPatch((draft) => {
                draft.integrations = {
                  ...(draft.integrations || {}),
                  googleSheets: {
                    ...(draft.integrations?.googleSheets || {}),
                    enabled: integrations.googleSheets?.enabled === true,
                    spreadsheetId: integrations.googleSheets?.spreadsheetId || '',
                    serviceAccountEmail: e.target.value
                  }
                }
              })}
              placeholder="service-account@example.iam.gserviceaccount.com"
            />
          </label>
          <label className="block text-xs text-slate-400">
            Service account JSON
            <textarea
              className={`${inputClass} mt-1 h-24 font-mono`}
              value={googleSheetsCredential}
              onChange={(e) => setGoogleSheetsCredential(e.target.value)}
              placeholder={connectorCredentialPresence[googleSheetsCredentialAccount] ? 'Stored. Paste JSON to replace.' : 'Paste JSON to store securely'}
            />
            <span className="mt-1 block text-xs text-slate-500">
              {credentialStatusText(googleSheetsCredentialAccount, connectorCredentialPresence, googleSheetsCredential)}
            </span>
          </label>
        </div>
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
      <p className="text-xs text-slate-500">API keys and connector tokens are stored in the OS credential store via keytar, not in settings.json.</p>
      <div className="rounded border border-slate-800 p-3 text-sm text-slate-300">
        <div className="font-medium text-slate-200">Third-party notices</div>
        <p className="mt-1 text-xs text-slate-500">
          Includes Microsoft Webwright (MIT) and bundled runtime components. See repository{' '}
          <span className="text-slate-400">third_party/NOTICE.md</span> and bundled{' '}
          <span className="text-slate-400">THIRD_PARTY_NOTICES.txt</span> for details.
        </p>
        <button
          type="button"
          className="mt-2 rounded bg-slate-800 px-3 py-1.5 text-xs hover:bg-slate-700"
          onClick={async () => {
            const result = await window.electronAPI?.openThirdPartyNotices()
            if (!result?.ok) {
              window.alert(result?.message ?? 'Third-party notices file is not available in this build.')
            }
          }}
        >
          Open bundled notices file
        </button>
      </div>
    </div>
  )
}

function IntegrationRow({
  label,
  enabled,
  baseUrl,
  onChange,
  children
}: {
  label: string
  enabled: boolean
  baseUrl: string
  onChange: (next: IntegrationConfig) => void
  children?: ReactNode
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
      {children}
    </div>
  )
}

async function storeCredentialDraft(service: string, account: string, password: string, label: string): Promise<void> {
  if (!window.electronAPI?.credentialSet) {
    throw new Error(`${label} can be stored only in the desktop app secure credential store.`)
  }
  const result = await window.electronAPI.credentialSet(service, account, password)
  if (!result.ok) {
    throw new Error(result.message || `Could not store ${label}.`)
  }
}

function getConnectorCredentialAccount(
  metadata: ConnectorCredentialsResponse | undefined,
  connectorId: 'testrail' | 'googleSheets',
  kind: 'apiToken' | 'serviceAccountJson'
): string {
  const fromWorker = metadata?.connectors[connectorId]?.credentials.find((credential) => credential.kind === kind)
  if (fromWorker?.account) return fromWorker.account
  if (connectorId === 'testrail') return DEFAULT_CONNECTOR_ACCOUNTS.testrail.apiToken
  return DEFAULT_CONNECTOR_ACCOUNTS.googleSheets.serviceAccountJson
}

function credentialStatusText(account: string, presence: Record<string, boolean>, draftValue: string): string {
  if (draftValue.trim()) return 'Ready to store in OS credential store on save.'
  return presence[account] ? 'Stored in OS credential store.' : 'No credential stored.'
}

function getHealthCheck(health: HealthResponse | null, key: string): HealthCheck | null {
  const value = health?.[key]
  return typeof value === 'object' && value !== null ? value : null
}

function getAutoApplyProjectIds(settings: AppSettings['self_healing'] | undefined): string[] {
  return Array.from(new Set([
    ...normalizeProjectIds(settings?.autoApplyProjectIds),
    ...normalizeProjectIds(settings?.auto_apply_project_ids)
  ]))
}

function normalizeProjectIds(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item).trim()).filter(Boolean)
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


