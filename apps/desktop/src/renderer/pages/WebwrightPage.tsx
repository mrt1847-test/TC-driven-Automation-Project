import { Fragment, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { WebwrightRunErrorPanel } from '@/components/WebwrightRunErrorPanel'
import {
  api,
  connectLogStream,
  getApiErrorMessage,
  type PromptPreset,
  type TestCase,
  type WebwrightRun
} from '@/lib/api'
import { describeWebwrightRunError } from '@/lib/webwrightErrors'
import { useAppStore } from '@/store/appStore'

type AppSettings = {
  webwright?: {
    apiProvider?: string
    modelName?: string
    [key: string]: unknown
  }
  [key: string]: unknown
}

type LlmCheckState = {
  status: 'idle' | 'ok' | 'error'
  message: string
}

type PromptPresetDraft = {
  category: string
  name: string
  guidance: string
}

const DEFAULT_PROMPT_PRESET_ID = 'preset_builtin_general'
const EMPTY_PROMPT_PRESETS: PromptPreset[] = []

const legacyPromptPresetIds: Record<string, string> = {
  general: 'preset_builtin_general',
  'login-required': 'preset_builtin_login',
  'search-flow': 'preset_builtin_search',
  'crud-flow': 'preset_builtin_crud',
  'assertion-heavy': 'preset_builtin_assertion_heavy'
}

const statusStyles: Record<string, string> = {
  imported: 'bg-slate-700 text-slate-100',
  pending: 'bg-slate-700 text-slate-100',
  queued: 'bg-slate-700 text-slate-100',
  webwright_running: 'bg-blue-700 text-white',
  running: 'bg-blue-700 text-white',
  webwright_completed: 'bg-green-700 text-white',
  completed: 'bg-green-700 text-white',
  webwright_failed: 'bg-red-700 text-white',
  failed: 'bg-red-700 text-white',
  cancelled: 'bg-yellow-700 text-white'
}

function statusClass(status: string) {
  return statusStyles[status] || 'bg-slate-800 text-slate-200'
}

function runTime(run?: WebwrightRun) {
  if (!run?.started_at) return 'No run'
  return new Date(run.started_at).toLocaleString()
}

function canCancel(status: string) {
  return ['queued', 'pending', 'running'].includes(status)
}

function artifactPath(outputPath: string | undefined, fileName: string) {
  if (!outputPath) return ''
  const separator = outputPath.includes('\\') ? '\\' : '/'
  return `${outputPath.replace(/[\\/]+$/, '')}${separator}${fileName}`
}

function providerLabel(provider: string) {
  return provider === 'azure-openai'
    ? 'Azure OpenAI'
    : provider.charAt(0).toUpperCase() + provider.slice(1)
}

function normalizePromptPresetId(id?: string | null) {
  const trimmed = (id || '').trim()
  if (!trimmed) return DEFAULT_PROMPT_PRESET_ID
  return legacyPromptPresetIds[trimmed] || trimmed
}

function promptPresetOptionLabel(preset: PromptPreset) {
  return preset.isBuiltin ? preset.name : `${preset.name} (Project)`
}

function slugPromptPreset(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40) || 'preset'
}

function makeProjectPromptPresetId(draft: PromptPresetDraft) {
  return [
    'preset_project',
    slugPromptPreset(draft.category),
    slugPromptPreset(draft.name),
    Date.now().toString(36)
  ].join('_')
}

function toProjectPresetInput(preset: PromptPreset) {
  return {
    id: preset.id,
    category: preset.category,
    name: preset.name,
    guidance: preset.guidance
  }
}

export function WebwrightPage() {
  const project = useAppStore((s) => s.currentProject)
  const appendLog = useAppStore((s) => s.appendLog)
  const storeSelectedCase = useAppStore((s) => s.selectedCase)
  const setSelectedCase = useAppStore((s) => s.setSelectedCase)
  const [selected, setSelected] = useState<string[]>([])
  const [apiProvider, setApiProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const [modelName, setModelName] = useState('')
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [modelStatus, setModelStatus] = useState('Load available models to verify access for the selected provider key.')
  const [llmCheck, setLlmCheck] = useState<LlmCheckState>({
    status: 'idle',
    message: 'Provider credentials not checked yet.'
  })
  const [batchPrompt, setBatchPrompt] = useState('')
  const [casePromptOverrides, setCasePromptOverrides] = useState<Record<string, string>>({})
  const [promptPresetId, setPromptPresetId] = useState(DEFAULT_PROMPT_PRESET_ID)
  const [promptDraft, setPromptDraft] = useState<PromptPresetDraft>({
    category: 'custom',
    name: '',
    guidance: ''
  })
  const [promptDirty, setPromptDirty] = useState(false)
  const [promptStatus, setPromptStatus] = useState('Prompt composer loading from Worker.')
  const [runActionError, setRunActionError] = useState<string | null>(null)
  const seededCaseIdRef = useRef<string | null>(null)
  const promptComposerProjectRef = useRef<string | null>(null)
  const qc = useQueryClient()
  const selectedCaseId = storeSelectedCase?.project_id === project?.id ? storeSelectedCase.id : null

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: api.settings.get
  })
  const { data: cases = [] } = useQuery({
    queryKey: ['cases', project?.id],
    queryFn: () => api.cases.list(project!.id),
    enabled: !!project,
    refetchInterval: 3000
  })
  const promptCase = cases.find((c) => c.id === selectedCaseId) || cases.find((c) => selected.includes(c.id))
  const caseOverride = promptCase ? casePromptOverrides[promptCase.id] || '' : ''

  const { data: runs = [] } = useQuery({
    queryKey: ['webwright-runs', project?.id],
    queryFn: () => api.webwright.list(project!.id),
    enabled: !!project,
    refetchInterval: 3000
  })
  const promptComposerQuery = useQuery({
    queryKey: ['prompt-composer', project?.id],
    queryFn: () => api.prompts.composer(project!.id),
    enabled: !!project
  })
  const promptPresetsQuery = useQuery({
    queryKey: ['prompt-presets', project?.id],
    queryFn: () => api.prompts.presets(project!.id),
    enabled: !!project
  })
  const promptPresets = promptPresetsQuery.data?.presets ?? EMPTY_PROMPT_PRESETS
  const selectedPromptPreset = promptPresets.find((preset) => preset.id === promptPresetId) || promptPresets[0] || null
  const selectedPresetIsProject = Boolean(selectedPromptPreset && !selectedPromptPreset.isBuiltin)
  const promptPreviewQuery = useQuery({
    queryKey: ['prompt-preview', project?.id, promptCase?.id, promptPresetId],
    queryFn: () => api.prompts.preview(project!.id, {
      caseId: promptCase!.id,
      presetId: promptPresetId || undefined
    }),
    enabled: !!project && !!promptCase && !!promptPresetId
  })

  useEffect(() => {
    const savedProvider = (settings as AppSettings | undefined)?.webwright?.apiProvider
    if (savedProvider) setApiProvider(savedProvider)
    setModelName((settings as AppSettings | undefined)?.webwright?.modelName || '')
  }, [settings])

  useEffect(() => {
    if (!project) {
      promptComposerProjectRef.current = null
      setBatchPrompt('')
      setCasePromptOverrides({})
      setPromptPresetId(DEFAULT_PROMPT_PRESET_ID)
      setPromptDirty(false)
      return
    }
    if (!promptComposerQuery.data) return
    const switchingProject = promptComposerProjectRef.current !== project.id
    if (!switchingProject && promptDirty) return
    promptComposerProjectRef.current = project.id
    setBatchPrompt(promptComposerQuery.data.batchPrompt || '')
    setCasePromptOverrides(promptComposerQuery.data.caseOverrides || {})
    setPromptPresetId(normalizePromptPresetId(promptComposerQuery.data.selectedPresetId))
    setPromptDirty(false)
    setPromptStatus('Prompt composer loaded from Worker.')
  }, [project, promptComposerQuery.data, promptDirty])

  useEffect(() => {
    if (!promptPresets.length) return
    if (promptPresets.some((preset) => preset.id === promptPresetId)) return
    setPromptPresetId(promptPresets[0]?.id || DEFAULT_PROMPT_PRESET_ID)
    setPromptDirty(true)
    setPromptStatus('Prompt preset changed. Save Prompt to persist the selected preset.')
  }, [promptPresets, promptPresetId])

  useEffect(() => {
    if (!selectedPromptPreset) {
      setPromptDraft({ category: 'custom', name: '', guidance: '' })
      return
    }
    setPromptDraft({
      category: selectedPromptPreset.category,
      name: selectedPromptPreset.name,
      guidance: selectedPromptPreset.guidance
    })
  }, [selectedPromptPreset])

  useEffect(() => {
    if (!selectedCaseId || seededCaseIdRef.current === selectedCaseId) return
    if (!cases.some((c) => c.id === selectedCaseId)) return
    seededCaseIdRef.current = selectedCaseId
    setSelected((current) => current.includes(selectedCaseId) ? current : [selectedCaseId])
  }, [cases, selectedCaseId])

  const runMut = useMutation({
    mutationFn: async (caseIds: string[]) => {
      const res = await api.webwright.run(project!.id, { caseIds, presetId: promptPresetId || undefined })
      connectLogStream(res.jobId, appendLog)
      return res
    },
    onMutate: () => setRunActionError(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['webwright-runs', project?.id] })
    },
    onError: (error) => {
      setRunActionError(getApiErrorMessage(error, 'Could not queue the Webwright run.'))
    }
  })

  const retryMut = useMutation({
    mutationFn: async (runId: string) => {
      const res = await api.webwright.retry(project!.id, runId)
      connectLogStream(res.jobId, appendLog)
      return res
    },
    onMutate: () => setRunActionError(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['webwright-runs', project?.id] })
    },
    onError: (error) => {
      setRunActionError(getApiErrorMessage(error, 'Could not retry the Webwright run.'))
    }
  })

  const cancelMut = useMutation({
    mutationFn: (runId: string) => api.webwright.cancel(project!.id, runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['webwright-runs', project?.id] })
    }
  })

  const saveLlmMut = useMutation({
    mutationFn: async () => {
      const current = (settings as AppSettings | undefined) || await api.settings.get() as AppSettings
      const next: AppSettings = {
        ...current,
        webwright: {
          ...(current.webwright || {}),
          apiProvider,
          modelName
        }
      }
      const saved = await api.settings.update(next) as AppSettings
      if (apiKey) {
        const stored = await window.electronAPI?.credentialSet('tc-studio', apiProvider, apiKey)
        if (!stored?.ok) {
          throw new Error(
            stored?.message ?? 'Could not store API key. Run the desktop app (not the browser) and retry.'
          )
        }
        setApiKey('')
      }
      return saved
    },
    onSuccess: (saved) => {
      qc.setQueryData(['settings'], saved)
      qc.invalidateQueries({ queryKey: ['settings'] })
      setLlmCheck({
        status: 'ok',
        message: apiKey ? 'Provider and API key saved.' : 'Provider saved. Existing key was not changed.'
      })
    },
    onError: (error) => {
      setLlmCheck({
        status: 'error',
        message: error instanceof Error ? error.message : 'Provider credential save failed.'
      })
    }
  })

  const loadModelsMut = useMutation({
    mutationFn: async () => {
      if (apiKey) {
        const stored = await window.electronAPI?.credentialSet('tc-studio', apiProvider, apiKey)
        if (!stored?.ok) {
          throw new Error(stored?.message || 'Could not store the API key before loading models.')
        }
        setApiKey('')
      }
      const result = await window.electronAPI?.providerModels(apiProvider)
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

  const checkLlmMut = useMutation({
    mutationFn: async () => {
      const saved = await saveLlmMut.mutateAsync()
      await api.settings.validate()
      const storedKey = await window.electronAPI?.credentialGet('tc-studio', apiProvider)
      if (!storedKey?.ok) {
        throw new Error(
          storedKey?.message ?? `No API key found for ${providerLabel(apiProvider)}. Enter a key and click Check Key again.`
        )
      }
      return saved
    },
    onSuccess: () => {
      setLlmCheck({
        status: 'ok',
        message: `${providerLabel(apiProvider)} key is stored securely (Credential Manager or encrypted app store).`
      })
    },
    onError: (error) => {
      setLlmCheck({
        status: 'error',
        message: error instanceof Error ? error.message : 'Provider credential check failed.'
      })
    }
  })

  const savePromptMut = useMutation({
    mutationFn: async () => {
      if (!project) throw new Error('Select a project first.')
      const cleanedOverrides = Object.fromEntries(
        Object.entries(casePromptOverrides).filter(([, value]) => value.trim().length > 0)
      )
      const composer = await api.prompts.saveComposer(project.id, {
        batchPrompt,
        selectedPresetId: promptPresetId || null,
        caseOverrides: cleanedOverrides
      })
      return { projectId: project.id, composer }
    },
    onSuccess: ({ projectId, composer }) => {
      qc.setQueryData(['prompt-composer', projectId], composer)
      qc.invalidateQueries({ queryKey: ['prompt-preview', projectId] })
      setPromptDirty(false)
      setPromptStatus('Prompt composer saved to Worker.')
    },
    onError: (error) => {
      setPromptStatus(getApiErrorMessage(error, 'Prompt composer save failed.'))
    }
  })

  const savePresetMut = useMutation({
    mutationFn: async () => {
      if (!project) throw new Error('Select a project first.')
      const category = promptDraft.category.trim()
      const name = promptDraft.name.trim()
      const guidance = promptDraft.guidance.trim()
      if (!category || !name || !guidance) {
        throw new Error('Project preset requires category, name, and guidance.')
      }
      const presetId = selectedPresetIsProject && selectedPromptPreset?.id
        ? selectedPromptPreset.id
        : makeProjectPromptPresetId({ category, name, guidance })
      const presets = [
        ...promptPresets
          .filter((preset) => !preset.isBuiltin && preset.id !== presetId)
          .map(toProjectPresetInput),
        { id: presetId, category, name, guidance }
      ]
      const response = await api.prompts.savePresets(project.id, { presets })
      return { projectId: project.id, presetId, response }
    },
    onSuccess: ({ projectId, presetId, response }) => {
      qc.setQueryData(['prompt-presets', projectId], response)
      qc.invalidateQueries({ queryKey: ['prompt-preview', projectId] })
      setPromptPresetId(presetId)
      setPromptDirty(true)
      setPromptStatus('Project prompt preset saved. Save Prompt to persist the selected preset.')
    },
    onError: (error) => {
      setPromptStatus(getApiErrorMessage(error, 'Project prompt preset save failed.'))
    }
  })

  const deletePresetMut = useMutation({
    mutationFn: async () => {
      if (!project) throw new Error('Select a project first.')
      if (!selectedPromptPreset || selectedPromptPreset.isBuiltin) {
        throw new Error('Select a project preset to delete.')
      }
      const presets = promptPresets
        .filter((preset) => !preset.isBuiltin && preset.id !== selectedPromptPreset.id)
        .map(toProjectPresetInput)
      const response = await api.prompts.savePresets(project.id, { presets })
      return { projectId: project.id, response }
    },
    onSuccess: ({ projectId, response }) => {
      const fallbackPresetId = response.presets.find((preset) => preset.id === DEFAULT_PROMPT_PRESET_ID)?.id
        || response.presets[0]?.id
        || DEFAULT_PROMPT_PRESET_ID
      qc.setQueryData(['prompt-presets', projectId], response)
      qc.invalidateQueries({ queryKey: ['prompt-preview', projectId] })
      setPromptPresetId(fallbackPresetId)
      setPromptDirty(true)
      setPromptStatus('Project prompt preset deleted. Save Prompt to persist the selected preset.')
    },
    onError: (error) => {
      setPromptStatus(getApiErrorMessage(error, 'Project prompt preset delete failed.'))
    }
  })

  function runForCase(caseId: string) {
    const nextCase = cases.find((c) => c.id === caseId)
    if (nextCase) setSelectedCase(nextCase)
    setSelected([caseId])
    runMut.mutate([caseId])
  }

  function latestRun(caseId: string) {
    return runs
      .filter((r) => r.test_case_id === caseId)
      .sort((a, b) => {
        const left = Date.parse(a.started_at || a.ended_at || '')
        const right = Date.parse(b.started_at || b.ended_at || '')
        return (Number.isNaN(right) ? 0 : right) - (Number.isNaN(left) ? 0 : left)
      })[0]
  }

  if (!project) return <p>Select a project first.</p>

  const promptApiError = promptComposerQuery.isError
    ? getApiErrorMessage(promptComposerQuery.error, 'Prompt composer load failed.')
    : promptPresetsQuery.isError
      ? getApiErrorMessage(promptPresetsQuery.error, 'Prompt preset load failed.')
      : null
  const promptPreview = !promptCase
    ? 'Select a TC to preview the prompt payload.'
    : promptPreviewQuery.isLoading
      ? 'Loading Worker prompt preview...'
      : promptPreviewQuery.isError
        ? getApiErrorMessage(promptPreviewQuery.error, 'Prompt preview failed.')
        : promptPreviewQuery.data?.prompt || 'No prompt preview available.'
  const promptStatusClass = promptApiError || promptStatus.toLowerCase().includes('failed')
    ? 'text-red-400'
    : promptDirty
      ? 'text-amber-400'
      : 'text-slate-500'

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Webwright Generate</h2>
        <button
          className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
          disabled={!selected.length || runMut.isPending}
          onClick={() => runMut.mutate(selected)}
        >
          {runMut.isPending ? 'Starting...' : 'Run Selected'}
        </button>
      </div>
      <section className="rounded border border-slate-800 bg-slate-900 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-44 flex-1 text-xs text-slate-400">
            LLM provider
            <select
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
              value={apiProvider}
              onChange={(e) => {
                setApiProvider(e.target.value)
                setModelName('')
                setAvailableModels([])
                setModelStatus('Load available models to verify access for the selected provider key.')
                setLlmCheck({ status: 'idle', message: 'Provider credentials not checked yet.' })
              }}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="azure-openai">Azure OpenAI</option>
            </select>
          </label>
          <label className="min-w-64 flex-[2] text-xs text-slate-400">
            API key
            <input
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
              type="password"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value)
                setLlmCheck({ status: 'idle', message: 'Provider credentials not checked yet.' })
              }}
              placeholder="Stored in OS credential store"
            />
          </label>
          <label className="min-w-64 flex-[2] text-xs text-slate-400">
            Model
            <input
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
              list="webwright-run-model-options"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              placeholder="Use model config default"
            />
            <datalist id="webwright-run-model-options">
              {availableModels.map((model) => <option key={model} value={model} />)}
            </datalist>
          </label>
          <button
            className="px-3 py-2 bg-slate-700 rounded text-sm disabled:opacity-50"
            disabled={loadModelsMut.isPending || saveLlmMut.isPending || checkLlmMut.isPending}
            onClick={() => loadModelsMut.mutate()}
          >
            {loadModelsMut.isPending ? 'Loading...' : 'Load models'}
          </button>
          <button
            className="px-3 py-2 bg-slate-700 rounded text-sm disabled:opacity-50"
            disabled={loadModelsMut.isPending || saveLlmMut.isPending || checkLlmMut.isPending}
            onClick={() => saveLlmMut.mutate()}
          >
            {saveLlmMut.isPending ? 'Saving...' : 'Save LLM'}
          </button>
          <button
            className="px-3 py-2 bg-blue-600 rounded text-sm disabled:opacity-50"
            disabled={loadModelsMut.isPending || saveLlmMut.isPending || checkLlmMut.isPending}
            onClick={() => checkLlmMut.mutate()}
          >
            {checkLlmMut.isPending ? 'Checking...' : 'Check Key'}
          </button>
        </div>
        <div className={`mt-2 text-xs ${llmCheck.status === 'ok' ? 'text-green-400' : llmCheck.status === 'error' ? 'text-red-400' : 'text-slate-500'}`}>
          {llmCheck.message}
        </div>
        <div className={`mt-1 text-xs ${
          availableModels.length && modelName && !availableModels.includes(modelName)
            ? 'text-amber-400'
            : 'text-slate-500'
        }`}>
          {availableModels.length && modelName && !availableModels.includes(modelName)
            ? `${modelName} is not available for the stored key. Select one of the ${availableModels.length} available models.`
            : modelStatus}
        </div>
      </section>
      <section className="rounded border border-slate-800 bg-slate-900 p-3 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium">Prompt Composer</h3>
            <p className="text-xs text-slate-500">
              {promptCase
                ? `Override target: ${promptCase.automation_key} - ${promptCase.title}`
                : 'Select a TC to edit a per-case override.'}
            </p>
          </div>
          <button
            className="px-3 py-2 bg-blue-600 rounded text-sm disabled:opacity-50"
            disabled={savePromptMut.isPending || promptPresetsQuery.isLoading}
            onClick={() => savePromptMut.mutate()}
          >
            {savePromptMut.isPending ? 'Saving...' : 'Save Prompt'}
          </button>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <label className="block text-xs text-slate-400">
            Batch shared prompt
            <textarea
              className="mt-1 h-32 w-full resize-y rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
              value={batchPrompt}
              onChange={(e) => {
                setBatchPrompt(e.target.value)
                setPromptDirty(true)
                setPromptStatus('Prompt changes not saved yet.')
              }}
              placeholder="Shared domain hints, auth notes, selector preferences, assertion guidance..."
            />
          </label>
          <label className="block text-xs text-slate-400">
            Selected TC override
            <textarea
              className="mt-1 h-32 w-full resize-y rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 disabled:opacity-50"
              disabled={!promptCase}
              value={caseOverride}
              onChange={(e) => {
                if (!promptCase) return
                setCasePromptOverrides((current) => ({
                  ...current,
                  [promptCase.id]: e.target.value
                }))
                setPromptDirty(true)
                setPromptStatus('Prompt changes not saved yet.')
              }}
              placeholder="Extra instructions only for the selected TC..."
            />
          </label>
        </div>
        <div className="grid gap-3 lg:grid-cols-[minmax(0,240px)_1fr]">
          <label className="block text-xs text-slate-400">
            Prompt preset
            <select
              className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
              disabled={promptPresetsQuery.isLoading || !promptPresets.length}
              value={promptPresetId}
              onChange={(e) => {
                setPromptPresetId(e.target.value)
                setPromptDirty(true)
                setPromptStatus('Prompt changes not saved yet.')
              }}
            >
              {promptPresets.map((preset) => (
                <option key={preset.id} value={preset.id}>{promptPresetOptionLabel(preset)}</option>
              ))}
            </select>
            <div className="mt-2 text-xs text-slate-500">
              {selectedPromptPreset?.guidance || 'Worker prompt presets are not loaded yet.'}
            </div>
          </label>
          <div className="space-y-2 text-xs text-slate-400">
            <div className="grid gap-2 md:grid-cols-[minmax(0,160px)_minmax(0,1fr)]">
              <label>
                Preset category
                <input
                  className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
                  value={promptDraft.category}
                  onChange={(e) => setPromptDraft((current) => ({ ...current, category: e.target.value }))}
                  placeholder="custom"
                />
              </label>
              <label>
                Project preset name
                <input
                  className="mt-1 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
                  value={promptDraft.name}
                  onChange={(e) => setPromptDraft((current) => ({ ...current, name: e.target.value }))}
                  placeholder="Project flow preset"
                />
              </label>
            </div>
            <label className="block">
              Project preset guidance
              <textarea
                className="mt-1 h-20 w-full resize-y rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100"
                value={promptDraft.guidance}
                onChange={(e) => setPromptDraft((current) => ({ ...current, guidance: e.target.value }))}
                placeholder="Reusable prompt guidance for this project..."
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                className="px-3 py-2 bg-slate-700 rounded text-sm text-slate-100 disabled:opacity-50"
                disabled={savePresetMut.isPending || deletePresetMut.isPending || promptPresetsQuery.isLoading}
                onClick={() => savePresetMut.mutate()}
              >
                {savePresetMut.isPending
                  ? 'Saving...'
                  : selectedPresetIsProject ? 'Update Project Preset' : 'Save as Project Preset'}
              </button>
              <button
                className="px-3 py-2 bg-red-900 rounded text-sm text-red-50 disabled:opacity-50"
                disabled={!selectedPresetIsProject || deletePresetMut.isPending || savePresetMut.isPending}
                onClick={() => deletePresetMut.mutate()}
              >
                {deletePresetMut.isPending ? 'Deleting...' : 'Delete Project Preset'}
              </button>
            </div>
          </div>
        </div>
        <div className="text-xs text-slate-400">
          Prompt preview
          {promptDirty && (
            <span className="ml-2 text-amber-400">Preview reflects the last saved Worker prompt.</span>
          )}
            <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200">
              {promptPreview}
            </pre>
        </div>
        <div className={`text-xs ${promptStatusClass}`}>{promptApiError || promptStatus}</div>
      </section>
      {runActionError && (
        <div className="rounded border border-red-800 bg-red-950/30 p-3 text-sm text-red-100">
          <div className="font-medium">Run request failed</div>
          <div className="mt-1 whitespace-pre-wrap break-words text-xs">{runActionError}</div>
          <div className="mt-2 text-xs text-red-200/80">
            Selected TCs and saved prompt settings were not cleared. Fix the issue above, then retry Run or Retry.
          </div>
        </div>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-400">
            <th className="w-8"></th>
            <th className="py-2">TC</th>
            <th>Key</th>
            <th>Case Status</th>
            <th>Latest Run</th>
            <th>Run Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const run = latestRun(c.id)
            const runStatus = run?.status || 'pending'
            const failedRun = runStatus === 'failed' ? run : undefined
            const failureGuide = failedRun ? describeWebwrightRunError(failedRun.error_message) : null
            return (
              <Fragment key={c.id}>
                <tr className="border-t border-slate-800">
                  <td><input type="checkbox" checked={selected.includes(c.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, c.id] : selected.filter((id) => id !== c.id))} /></td>
                  <td className="py-2">
                    <button
                      type="button"
                      className={`text-left font-medium hover:text-blue-300 ${selectedCaseId === c.id ? 'text-blue-300' : ''}`}
                      onClick={() => setSelectedCase(c)}
                    >
                      {c.source_case_id}
                    </button>
                    <div className="text-xs text-slate-500">{c.title}</div>
                  </td>
                  <td>{c.automation_key}</td>
                  <td><span className={`rounded px-2 py-1 text-xs ${statusClass(c.status)}`}>{c.status}</span></td>
                  <td className="text-xs text-slate-400">{runTime(run)}</td>
                  <td>
                    <span className={`rounded px-2 py-1 text-xs ${statusClass(runStatus)}`}>{runStatus}</span>
                    {failureGuide && (
                      <div className="mt-1 text-[11px] text-red-300">{failureGuide.title}</div>
                    )}
                  </td>
                  <td className="space-x-2">
                    <button className="text-blue-400 disabled:text-slate-600" disabled={runMut.isPending} onClick={() => runForCase(c.id)}>Run</button>
                    {run && canCancel(run.status) && (
                      <button className="text-red-400 disabled:text-slate-600" disabled={cancelMut.isPending} onClick={() => cancelMut.mutate(run.id)}>Stop</button>
                    )}
                    {run?.output_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(run.output_path!)}>Folder</button>}
                    {run?.final_script_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(run.final_script_path!)}>Script</button>}
                    {run?.trajectory_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(run.trajectory_path!)}>Trajectory</button>}
                    {run?.output_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(artifactPath(run.output_path, 'stdout.log'))}>Stdout</button>}
                    {run?.output_path && <button className="text-slate-400" onClick={() => window.electronAPI?.openPath(artifactPath(run.output_path, 'stderr.log'))}>Stderr</button>}
                    {run?.status === 'failed' && run.id && (
                      <button className="text-yellow-400 disabled:text-slate-600" disabled={retryMut.isPending} onClick={() => retryMut.mutate(run.id)}>Retry</button>
                    )}
                  </td>
                </tr>
                {failedRun && (
                  <tr className="border-t border-slate-900">
                    <td colSpan={7} className="py-2">
                      <WebwrightRunErrorPanel
                        run={failedRun}
                        onRetry={failedRun.id ? () => retryMut.mutate(failedRun.id) : undefined}
                        retryPending={retryMut.isPending}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
          {!cases.length && (
            <tr className="border-t border-slate-800">
              <td colSpan={7} className="py-6 text-center text-slate-400">No test cases imported yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
