import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { WebwrightRunErrorPanel } from '@/components/WebwrightRunErrorPanel'
import { api, getApiErrorMessage, type StructureValidationResponse, type TestCase, type WebwrightRun } from '@/lib/api'
import { caseDeepLink, useAutomationKeyDeepLink } from '@/lib/caseDeepLink'
import { useAppStore } from '@/store/appStore'

type TestStep = {
  index: number
  action: string
  expected?: string
}

type RawActionRow = {
  id: string
  type: string
  selector?: string
  target?: string
  value?: string
  source_line?: number
  order_index?: number
}

type MappingRow = {
  tc_step_index: number
  action_ids?: string[]
  normalized_step_id?: string
  normalized_step_name?: string
  pom_method_name?: string
  status: string
}

type MappingDraftRow = {
  tc_step_index: number
  action_id: string
  normalized_step_name: string
  pom_method_name: string
  status: string
}

type ValidationIssue = {
  severity: 'error' | 'warning' | 'info'
  source?: 'draft' | 'worker'
  step?: number
  file?: string
  kind?: string
  message: string
}

type SelectorCandidate = {
  type: string
  value: string
  confidence: number
}

export function MappingPage() {
  const navigate = useNavigate()
  const project = useAppStore((s) => s.currentProject)
  const storeSelectedCase = useAppStore((s) => s.selectedCase)
  const setSelectedCase = useAppStore((s) => s.setSelectedCase)
  const [mappingDraft, setMappingDraft] = useState<MappingDraftRow[]>([])
  const [mappingApiError, setMappingApiError] = useState<string | null>(null)
  const [mappingApiNotice, setMappingApiNotice] = useState<string | null>(null)
  const qc = useQueryClient()
  const selectedCaseId = storeSelectedCase?.project_id === project?.id ? storeSelectedCase.id : ''

  const { data: cases = [] } = useQuery({
    queryKey: ['cases', project?.id],
    queryFn: () => api.cases.list(project!.id),
    enabled: !!project
  })
  const deepLink = useAutomationKeyDeepLink(cases)

  useEffect(() => {
    if (!project || cases.length === 0) return
    if (deepLink.requestedAutomationKey) return
    const storedInProject = storeSelectedCase?.project_id === project.id
      && cases.some((item) => item.id === storeSelectedCase.id)
    if (storedInProject) return
    setSelectedCase(cases[0])
  }, [cases, deepLink.requestedAutomationKey, project?.id, setSelectedCase, storeSelectedCase?.id, storeSelectedCase?.project_id])

  const selectedCase = cases.find((c) => c.id === selectedCaseId)
    || deepLink.resolvedCase
    || (deepLink.requestedAutomationKey ? undefined : cases[0])

  const { data: actions = [] } = useQuery({
    queryKey: ['actions', project?.id, selectedCase?.id],
    queryFn: () => api.mapping.actions(project!.id, selectedCase!.id),
    enabled: !!project && !!selectedCase
  })

  const { data: mappings = [] } = useQuery({
    queryKey: ['mappings', project?.id, selectedCase?.id],
    queryFn: () => api.mapping.get(project!.id, selectedCase!.id),
    enabled: !!project && !!selectedCase
  })

  const {
    data: workerValidation,
    error: workerValidationError,
    isFetching: workerValidationFetching
  } = useQuery({
    queryKey: ['structure-validation', project?.id, selectedCase?.id],
    queryFn: () => api.mapping.validateStructure(project!.id, selectedCase!.id),
    enabled: !!project && !!selectedCase
  })

  const { data: runs = [] } = useQuery({
    queryKey: ['webwright-runs', project?.id],
    queryFn: () => api.webwright.list(project!.id),
    enabled: !!project,
    refetchInterval: 3000
  })

  const normalizeMut = useMutation({
    mutationFn: () => api.mapping.normalize(project!.id, selectedCase!.id),
    onMutate: () => {
      setMappingApiError(null)
      setMappingApiNotice(null)
    },
    onSuccess: () => {
      setMappingApiNotice('Auto Map refreshed mappings for the selected TC.')
      qc.invalidateQueries({ queryKey: ['mappings', project?.id, selectedCase?.id] })
      qc.invalidateQueries({ queryKey: ['actions', project?.id, selectedCase?.id] })
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['structure-validation', project?.id, selectedCase?.id] })
    },
    onError: (error) => {
      setMappingApiNotice(null)
      setMappingApiError(mappingApiFailureMessage('Auto Map', error))
    }
  })

  const steps = parseSteps(selectedCase)
  const run = latestRun(runs, selectedCase?.id)

  useEffect(() => {
    setMappingDraft(buildMappingDraft(mappings as MappingRow[], steps))
  }, [mappings, selectedCase?.id])

  useEffect(() => {
    setMappingApiError(null)
    setMappingApiNotice(null)
  }, [selectedCase?.id])

  const saveMappingMut = useMutation({
    mutationFn: () => {
      const actionRows = actions as RawActionRow[]
      const actionById = new Map(actionRows.map((action) => [action.id, action]))
      const body = {
        mappings: mappingDraft.map((mapping) => ({
          tc_step_index: mapping.tc_step_index,
          action_ids: mapping.action_id ? [mapping.action_id] : [],
          normalized_step_id: `flow_${String(mapping.tc_step_index).padStart(3, '0')}`,
          normalized_step_name: mapping.normalized_step_name || `step_${mapping.tc_step_index}`,
          pom_method_name: mapping.pom_method_name || mapping.normalized_step_name || `step_${mapping.tc_step_index}`,
          status: mapping.status
        })),
        actions: actionRows
          .filter((action) => actionById.has(action.id))
          .map((action) => ({
            id: action.id,
            type: action.type,
            target: action.target,
            selector: action.selector,
            value: action.value,
            source_line: action.source_line,
            order_index: action.order_index ?? 0
          }))
      }
      return api.mapping.save(project!.id, selectedCase!.id, body)
    },
    onMutate: () => {
      setMappingApiError(null)
      setMappingApiNotice(null)
    },
    onSuccess: () => {
      setMappingApiNotice('Mapping edits saved and refreshed for the selected TC.')
      qc.invalidateQueries({ queryKey: ['mappings', project?.id, selectedCase?.id] })
      qc.invalidateQueries({ queryKey: ['actions', project?.id, selectedCase?.id] })
      qc.invalidateQueries({ queryKey: ['cases', project?.id] })
      qc.invalidateQueries({ queryKey: ['structure-validation', project?.id, selectedCase?.id] })
    },
    onError: (error) => {
      setMappingApiNotice(null)
      setMappingApiError(mappingApiFailureMessage('Save Edits', error))
    }
  })

  if (!project) return <p>Select a project first.</p>

  const flowReadyCount = mappingDraft.filter((mapping) => mapping.status === 'mapped' && mapping.action_id).length
  const pomReadyCount = mappingDraft.filter((mapping) => mapping.pom_method_name.trim()).length
  const pageObjectName = selectedCase ? `${pascalName(selectedCase.automation_key)}Page` : 'PageObject'
  const localValidationIssues = validateStructureDraft(mappingDraft, steps)
  const workerValidationIssues = buildWorkerValidationIssues(workerValidation, workerValidationError)
  const validationIssues = [...localValidationIssues, ...workerValidationIssues]
  const errorCount = validationIssues.filter((issue) => issue.severity === 'error').length
  const warningCount = validationIssues.filter((issue) => issue.severity === 'warning').length

  function rerunInGenerateRaw() {
    if (!selectedCase) return
    setSelectedCase(selectedCase)
    navigate(caseDeepLink('/webwright', selectedCase.automation_key))
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-[560px] flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-72 flex-1">
          <h2 className="text-2xl font-bold">Mapping & Structure</h2>
          <p className="text-xs text-slate-500">
            {selectedCase
              ? `${selectedCase.automation_key} - ${selectedCase.title}`
              : 'Select a TC to review mapping context.'}
          </p>
        </div>
        <select
          className="min-w-72 rounded border border-slate-700 bg-slate-950 p-2 text-sm"
          value={selectedCase?.id || ''}
          onChange={(e) => {
            const next = cases.find((c) => c.id === e.target.value)
            if (next) setSelectedCase(next)
          }}
        >
          {!selectedCase && <option value="">Select a TC</option>}
          {cases.map((c) => <option key={c.id} value={c.id}>{c.automation_key} - {c.title}</option>)}
        </select>
        <button
          className="px-4 py-2 bg-blue-600 rounded disabled:opacity-50"
          disabled={!selectedCase || normalizeMut.isPending}
          onClick={() => normalizeMut.mutate()}
        >
          {normalizeMut.isPending ? 'Mapping...' : 'Auto Map'}
        </button>
        <button
          className="px-4 py-2 bg-slate-700 rounded disabled:opacity-50"
          disabled={!selectedCase}
          onClick={rerunInGenerateRaw}
        >
          Rerun in Generate Raw
        </button>
      </div>

      <div className="grid min-h-0 flex-1 gap-3 xl:grid-cols-[minmax(220px,0.9fr)_minmax(260px,1fr)_minmax(280px,1fr)]">
        <section className="flex min-h-0 flex-col rounded border border-slate-800 bg-slate-900">
          <PaneHeader title="TC Context" meta={`${steps.length} step(s)`} />
          <div className="space-y-3 overflow-auto p-3">
            {selectedCase && (
              <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-400">
                <div className="font-medium text-slate-200">{selectedCase.source_case_id}</div>
                <div className="mt-1">{selectedCase.status}</div>
                {selectedCase.priority && <div className="mt-1">Priority: {selectedCase.priority}</div>}
                {selectedCase.start_url && <div className="mt-1 break-all">Start URL: {selectedCase.start_url}</div>}
              </div>
            )}
            {steps.map((step) => (
              <div key={step.index} className="border-b border-slate-800 pb-3 text-sm last:border-b-0">
                <div className="font-medium text-slate-100">{step.index}. {step.action}</div>
                {step.expected && <div className="mt-1 text-xs text-slate-400">{step.expected}</div>}
              </div>
            ))}
            {!steps.length && <EmptyPaneText>No TC steps available.</EmptyPaneText>}
          </div>
        </section>

        <section className="flex min-h-0 flex-col rounded border border-slate-800 bg-slate-900">
          <PaneHeader title="Raw Actions" meta={`${actions.length} action(s)`} />
          <div className="overflow-auto p-3">
            <RawEvidence run={run} />
            <SelectorCandidateViewer actions={actions as RawActionRow[]} run={run} />
            {(actions as RawActionRow[]).map((action, index) => (
              <div key={action.id} className="mb-3 rounded border border-slate-800 bg-slate-950 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-blue-300">{action.type}</span>
                  <span className="text-xs text-slate-500">#{action.order_index ?? index + 1}</span>
                </div>
                <div className="mt-2 break-all text-xs text-slate-400">{action.selector || action.target || 'No selector/target captured'}</div>
              </div>
            ))}
            {!actions.length && <EmptyPaneText>No raw actions found for the selected TC.</EmptyPaneText>}
          </div>
        </section>

        <section className="flex min-h-0 flex-col rounded border border-slate-800 bg-slate-900">
          <PaneHeader title="Normalized Flow" meta={`${flowReadyCount}/${mappingDraft.length} ready`} />
          <div className="overflow-auto p-3">
            <div className="mb-3 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h4 className="text-sm font-medium text-slate-100">Flow Editor</h4>
                  <div className="mt-1 text-xs text-slate-500">
                    {selectedCase ? `flow_${selectedCase.automation_key}` : 'No TC selected'}
                  </div>
                </div>
                <span className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">
                  {mappingDraft.length} step(s)
                </span>
              </div>
              <div className="mt-3 space-y-2">
                {mappingDraft.map((mapping, index) => (
                  <div key={`flow-${mapping.tc_step_index}`} className="grid gap-2 rounded border border-slate-800 bg-slate-900 p-2 text-xs lg:grid-cols-[44px_minmax(0,1fr)_112px]">
                    <div className="text-slate-500">#{index + 1}</div>
                    <input
                      className="min-w-0 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
                      value={mapping.normalized_step_name}
                      onChange={(e) => updateMappingDraft(mapping.tc_step_index, { normalized_step_name: e.target.value })}
                    />
                    <select
                      className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
                      value={mapping.status}
                      onChange={(e) => updateMappingDraft(mapping.tc_step_index, { status: e.target.value })}
                    >
                      <option value="mapped">mapped</option>
                      <option value="needs_review">needs_review</option>
                      <option value="unmapped">unmapped</option>
                    </select>
                    <div className="lg:col-span-3 text-slate-500">
                      TC step {mapping.tc_step_index}
                      {mapping.action_id ? ` -> ${rawActionLabel(actions as RawActionRow[], mapping.action_id)}` : ' -> no raw action'}
                    </div>
                  </div>
                ))}
                {!mappingDraft.length && <EmptyPaneText>No flow steps available. Run Auto Map to create a baseline.</EmptyPaneText>}
              </div>
            </div>
            <div className="mb-3 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h4 className="text-sm font-medium text-slate-100">Page Object Plan</h4>
                  <div className="mt-1 text-xs text-slate-500">{pageObjectName}</div>
                </div>
                <span className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">
                  {pomReadyCount}/{mappingDraft.length} method(s)
                </span>
              </div>
              <div className="mt-3 space-y-2">
                {mappingDraft.map((mapping) => (
                  <div key={`pom-${mapping.tc_step_index}`} className="rounded border border-slate-800 bg-slate-900 p-2 text-xs">
                    <div className="mb-2 text-slate-500">
                      Step {mapping.tc_step_index}: {mapping.normalized_step_name || `step_${mapping.tc_step_index}`}
                    </div>
                    <input
                      className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
                      value={mapping.pom_method_name}
                      onChange={(e) => updateMappingDraft(mapping.tc_step_index, { pom_method_name: e.target.value })}
                      placeholder={`method_for_step_${mapping.tc_step_index}`}
                    />
                  </div>
                ))}
                {!mappingDraft.length && <EmptyPaneText>No Page Object methods available. Run Auto Map to create a baseline.</EmptyPaneText>}
              </div>
            </div>
            <div className="mb-3 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h4 className="text-sm font-medium text-slate-100">Structure Validation</h4>
                  <div className="mt-1 text-xs text-slate-500">
                    {errorCount} error(s), {warningCount} warning(s)
                    {workerValidationFetching
                      ? ' - Worker checking'
                      : workerValidation
                        ? ` - Worker ${workerValidation.ok ? 'ready' : 'issues'}`
                        : ''}
                  </div>
                </div>
                <span className={`rounded px-2 py-1 text-xs ${validationStatusClass(errorCount, warningCount, workerValidationFetching)}`}>
                  {workerValidationFetching ? 'checking' : errorCount ? 'blocked' : warningCount ? 'review' : 'ready'}
                </span>
              </div>
              <div className="mt-3 space-y-2">
                {validationIssues.map((issue, index) => (
                  <div key={`${issue.severity}-${issue.step || 'global'}-${index}`} className={`rounded border p-2 text-xs ${validationIssueClass(issue.severity)}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="font-medium">{validationIssueTitle(issue)}</div>
                      {issue.source && (
                        <span className="rounded bg-slate-950 px-1.5 py-0.5 text-[10px] uppercase text-slate-400">
                          {issue.source}
                        </span>
                      )}
                    </div>
                    <div className="mt-1">{issue.message}</div>
                  </div>
                ))}
                {!validationIssues.length && workerValidationFetching && (
                  <div className="rounded border border-slate-800 bg-slate-950 p-2 text-xs text-slate-300">
                    Checking saved structure and generated-file status.
                  </div>
                )}
                {!validationIssues.length && !workerValidationFetching && (
                  <div className="rounded border border-green-800 bg-green-950/30 p-2 text-xs text-green-200">
                    Draft flow and Worker structure validation are ready for the selected TC.
                  </div>
                )}
              </div>
            </div>
            <div className="mb-3 flex items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-xs text-slate-400">
                Edit raw action links and detailed step metadata.
              </div>
              <button
                className="rounded bg-blue-600 px-3 py-2 text-xs disabled:opacity-50"
                disabled={!mappingDraft.length || saveMappingMut.isPending}
                type="button"
                onClick={() => saveMappingMut.mutate()}
              >
                {saveMappingMut.isPending ? 'Saving...' : 'Save Edits'}
              </button>
            </div>
            {(mappingApiError || mappingApiNotice) && (
              <MappingApiStatus
                error={mappingApiError}
                notice={mappingApiNotice}
                selectedCaseLabel={selectedCase?.automation_key || 'selected TC'}
              />
            )}
            {mappingDraft.map((mapping) => (
              <div key={mapping.tc_step_index} className="mb-3 rounded border border-slate-800 bg-slate-950 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">Step {mapping.tc_step_index}</span>
                  <span className={`rounded px-2 py-1 text-xs ${mapping.status === 'mapped' ? 'bg-green-700 text-white' : 'bg-yellow-700 text-white'}`}>
                    {mapping.status}
                  </span>
                </div>
                <label className="mt-3 block text-xs text-slate-400">
                  Raw action
                  <select
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2 text-xs text-slate-100"
                    value={mapping.action_id}
                    onChange={(e) => updateMappingDraft(mapping.tc_step_index, { action_id: e.target.value })}
                  >
                    <option value="">Unmapped</option>
                    {(actions as RawActionRow[]).map((action, index) => (
                      <option key={action.id} value={action.id}>
                        #{action.order_index ?? index + 1} {action.type} {action.selector || action.target || ''}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="mt-3 block text-xs text-slate-400">
                  Normalized step
                  <input
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2 text-xs text-slate-100"
                    value={mapping.normalized_step_name}
                    onChange={(e) => updateMappingDraft(mapping.tc_step_index, { normalized_step_name: e.target.value })}
                  />
                </label>
                <label className="mt-3 block text-xs text-slate-400">
                  Status
                  <select
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2 text-xs text-slate-100"
                    value={mapping.status}
                    onChange={(e) => updateMappingDraft(mapping.tc_step_index, { status: e.target.value })}
                  >
                    <option value="mapped">mapped</option>
                    <option value="needs_review">needs_review</option>
                    <option value="unmapped">unmapped</option>
                  </select>
                </label>
              </div>
            ))}
            {!mappingDraft.length && <EmptyPaneText>No normalized mappings yet. Run Auto Map to create a baseline.</EmptyPaneText>}
            {selectedCase?.status === 'needs_review' && (
              <div className="mt-3 rounded border border-yellow-700 bg-yellow-950/30 p-3 text-xs text-yellow-200">
                needs_review: step/action count mismatch
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )

  function updateMappingDraft(stepIndex: number, patch: Partial<MappingDraftRow>) {
    setMappingDraft((current) => current.map((mapping) => (
      mapping.tc_step_index === stepIndex ? { ...mapping, ...patch } : mapping
    )))
  }
}

function PaneHeader({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <span className="text-xs text-slate-500">{meta}</span>
    </div>
  )
}

function MappingApiStatus({
  error,
  notice,
  selectedCaseLabel
}: {
  error: string | null
  notice: string | null
  selectedCaseLabel: string
}) {
  if (error) {
    return (
      <div className="mb-3 rounded border border-red-800 bg-red-950/40 p-3 text-xs text-red-100">
        <div className="font-semibold text-red-200">Mapping API failed for {selectedCaseLabel}</div>
        <div className="mt-1 whitespace-pre-wrap break-words">{error}</div>
        <div className="mt-2 text-red-200/80">
          Your local mapping edits and selected TC were kept. Fix the highlighted issue or rerun Webwright, then try again.
        </div>
      </div>
    )
  }

  if (notice) {
    return (
      <div className="mb-3 rounded border border-green-800 bg-green-950/30 p-3 text-xs text-green-100">
        {notice}
      </div>
    )
  }

  return null
}

function EmptyPaneText({ children }: { children: string }) {
  return <p className="p-3 text-sm text-slate-500">{children}</p>
}

function RawEvidence({ run }: { run?: WebwrightRun }) {
  if (!run) {
    return (
      <div className="mb-3 rounded border border-slate-800 bg-slate-950 p-3 text-sm">
        <div className="font-medium text-slate-200">Artifact Evidence</div>
        <div className="mt-1 text-xs text-slate-500">No Webwright run found for this TC yet.</div>
      </div>
    )
  }

  return (
    <div className="mb-3 rounded border border-slate-800 bg-slate-950 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium text-slate-200">Artifact Evidence</div>
        <span className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">{run.status}</span>
      </div>
      <div className="mt-1 text-xs text-slate-500">{runTime(run)}</div>
      {run.status === 'failed' && (
        <div className="mt-2">
          <WebwrightRunErrorPanel run={run} compact />
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {run.output_path && <ArtifactButton label="Folder" path={run.output_path} />}
        {run.final_script_path && <ArtifactButton label="Script" path={run.final_script_path} />}
        {run.trajectory_path && <ArtifactButton label="Trajectory" path={run.trajectory_path} />}
        {run.output_path && <ArtifactButton label="Stdout" path={artifactPath(run.output_path, 'stdout.log')} />}
        {run.output_path && <ArtifactButton label="Stderr" path={artifactPath(run.output_path, 'stderr.log')} />}
        {run.output_path && <ArtifactButton label="Screenshots" path={run.output_path} />}
      </div>
      {!run.output_path && !run.final_script_path && !run.trajectory_path && (
        <div className="mt-2 text-xs text-slate-500">No artifact paths captured on the latest run.</div>
      )}
    </div>
  )
}

function SelectorCandidateViewer({ actions, run }: { actions: RawActionRow[]; run?: WebwrightRun }) {
  const actionable = actions.filter((action) => action.selector || action.target)

  return (
    <div className="mb-3 rounded border border-slate-800 bg-slate-950 p-3 text-sm">
      <div className="font-medium text-slate-200">Selector Candidates</div>
      <div className="mt-1 text-xs text-slate-500">
        Derived from raw Webwright actions for healing review. Worker C12-02 will enrich candidates later.
      </div>
      {!actionable.length && (
        <div className="mt-2 text-xs text-slate-500">No selector-bearing raw actions yet.</div>
      )}
      <div className="mt-3 space-y-3">
        {actionable.map((action, index) => {
          const bundle = buildSelectorCandidates(action)
          return (
            <div key={action.id} className="rounded border border-slate-800 bg-slate-900 p-2">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-medium text-blue-300">
                  #{action.order_index ?? index + 1} {action.type}
                </span>
                <span className="text-slate-500">{action.id}</span>
              </div>
              <div className="mt-2 overflow-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-slate-500">
                      <th className="pb-1 pr-2">Type</th>
                      <th className="pb-1 pr-2">Value</th>
                      <th className="pb-1">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bundle.candidates.map((candidate) => (
                      <tr key={`${action.id}-${candidate.type}-${candidate.value}`} className="border-t border-slate-800">
                        <td className="py-1 pr-2 text-slate-400">{candidate.type}</td>
                        <td className="py-1 pr-2 break-all text-slate-200">{candidate.value}</td>
                        <td className="py-1 text-slate-400">{Math.round(candidate.confidence * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {run?.output_path && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <ArtifactButton label="Trace" path={run.trajectory_path || run.output_path} />
                  <ArtifactButton label="Screenshots" path={run.output_path} />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ArtifactButton({ label, path }: { label: string; path: string }) {
  return (
    <button
      className="rounded bg-slate-800 px-2 py-1 text-xs text-blue-300 hover:bg-slate-700"
      type="button"
      onClick={() => window.electronAPI?.openPath(path)}
    >
      {label}
    </button>
  )
}

function buildSelectorCandidates(action: RawActionRow) {
  const primary = (action.selector || action.target || '').trim()
  const candidates: SelectorCandidate[] = []
  const seen = new Set<string>()

  function add(type: string, value: string, confidence: number) {
    const normalized = value.trim()
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    candidates.push({ type, value: normalized, confidence })
  }

  if (primary) {
    add('primary', primary, 1)
    if (primary.includes('get_by_role')) add('role', primary, 0.92)
    if (primary.includes('get_by_text') || primary.includes('text=')) add('text', primary, 0.72)
    if (primary.includes('locator(') || primary.includes('#') || primary.includes('.')) add('css', primary, 0.64)
    if (primary.includes('get_by_test_id')) add('test_id', primary, 0.9)
  }

  if (action.target && action.target !== primary) {
    add('target', action.target, 0.85)
    if (!primary.includes('text=') && !action.target.includes('page.')) {
      add('text', `text=${action.target}`, 0.68)
    }
  }

  if (action.value && action.type.toLowerCase().includes('fill')) {
    add('input_value', action.value, 0.55)
  }

  return { primary, candidates }
}

function parseSteps(testCase: TestCase | undefined): TestStep[] {
  if (!testCase) return []
  try {
    const parsed = JSON.parse(testCase.steps_json || '[]') as TestStep[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function buildMappingDraft(mappings: MappingRow[], steps: TestStep[]): MappingDraftRow[] {
  if (mappings.length) {
    return mappings
      .slice()
      .sort((a, b) => a.tc_step_index - b.tc_step_index)
      .map((mapping) => ({
        tc_step_index: mapping.tc_step_index,
        action_id: mapping.action_ids?.[0] || '',
        normalized_step_name: mapping.normalized_step_name || `step_${mapping.tc_step_index}`,
        pom_method_name: mapping.pom_method_name || mapping.normalized_step_name || `step_${mapping.tc_step_index}`,
        status: mapping.status || 'mapped'
      }))
  }

  return steps.map((step) => ({
    tc_step_index: step.index,
    action_id: '',
    normalized_step_name: slugStepName(step.action, step.index),
    pom_method_name: slugStepName(step.action, step.index),
    status: 'unmapped'
  }))
}

function slugStepName(action: string, index: number) {
  const slug = action
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40)
  return slug || `step_${index}`
}

function rawActionLabel(actions: RawActionRow[], actionId: string) {
  const action = actions.find((candidate) => candidate.id === actionId)
  if (!action) return 'missing raw action'
  const ordinal = action.order_index ? `#${action.order_index}` : action.type
  return `${ordinal} ${action.type} ${action.selector || action.target || ''}`.trim()
}

function validateStructureDraft(mappings: MappingDraftRow[], steps: TestStep[]): ValidationIssue[] {
  const issues: ValidationIssue[] = []

  if (!mappings.length) {
    issues.push({
      severity: 'error',
      source: 'draft',
      kind: 'draft_flow_missing',
      message: 'No normalized flow exists. Run Auto Map before structure review.'
    })
    return issues
  }

  if (steps.length && mappings.length !== steps.length) {
    issues.push({
      severity: 'warning',
      source: 'draft',
      kind: 'draft_step_count_mismatch',
      message: `TC has ${steps.length} step(s), but the normalized flow has ${mappings.length} step(s).`
    })
  }

  for (const mapping of mappings) {
    if (!mapping.action_id) {
      issues.push({
        severity: 'error',
        source: 'draft',
        step: mapping.tc_step_index,
        kind: 'draft_raw_action_missing',
        message: 'Missing raw action link.'
      })
    }
    if (!mapping.normalized_step_name.trim()) {
      issues.push({
        severity: 'error',
        source: 'draft',
        step: mapping.tc_step_index,
        kind: 'draft_step_name_missing',
        message: 'Normalized step name is empty.'
      })
    }
    if (!mapping.pom_method_name.trim()) {
      issues.push({
        severity: 'warning',
        source: 'draft',
        step: mapping.tc_step_index,
        kind: 'draft_pom_method_missing',
        message: 'Page Object method name is empty.'
      })
    }
    if (mapping.status === 'needs_review') {
      issues.push({
        severity: 'warning',
        source: 'draft',
        step: mapping.tc_step_index,
        kind: 'draft_step_needs_review',
        message: 'Step is marked needs_review.'
      })
    }
    if (mapping.status === 'unmapped') {
      issues.push({
        severity: 'error',
        source: 'draft',
        step: mapping.tc_step_index,
        kind: 'draft_step_unmapped',
        message: 'Step is marked unmapped.'
      })
    }
  }

  return issues
}

function buildWorkerValidationIssues(
  validation: StructureValidationResponse | undefined,
  error: unknown,
): ValidationIssue[] {
  if (error) {
    return [{
      severity: 'warning',
      source: 'worker',
      kind: 'worker_validation_unavailable',
      message: `Worker structure validation unavailable: ${getApiErrorMessage(error, 'Request failed.')}`
    }]
  }
  if (!validation) return []
  return (validation.issues || []).map(workerIssueToValidationIssue)
}

function workerIssueToValidationIssue(rawIssue: string): ValidationIssue {
  const separator = rawIssue.indexOf(':')
  const kind = separator >= 0 ? rawIssue.slice(0, separator) : rawIssue
  const detail = separator >= 0 ? rawIssue.slice(separator + 1) : ''
  const step = stepFromIssue(rawIssue)
  const file = generatedFileFromIssue(kind, detail)
  const severity = workerIssueSeverity(kind)
  return {
    severity,
    source: 'worker',
    step,
    file,
    kind,
    message: workerIssueMessage(kind, detail)
  }
}

function workerIssueSeverity(kind: string): ValidationIssue['severity'] {
  if (kind === 'flow_needs_review' || kind === 'mapping_needs_review') return 'warning'
  if (kind === 'generated_file_stale') return 'warning'
  if (kind.startsWith('generated_file_') && kind !== 'generated_file_generated') return 'error'
  if (kind === 'unsupported_action_requires_review') return 'warning'
  return 'error'
}

function workerIssueMessage(kind: string, detail: string) {
  if (kind === 'structured_flow_missing') return 'Saved Worker structure is missing a structured flow. Generate or sync structure before running generated tests.'
  if (kind === 'flow_needs_review') return 'Saved Worker structure is marked needs_review.'
  if (kind === 'mappings_missing') return 'Saved mappings are missing for this TC.'
  if (kind === 'mapping_needs_review') return 'Saved mapping row is marked needs_review.'
  if (kind === 'missing_step_name') return 'Saved mapping row is missing a normalized step or Page Object method name.'
  if (kind === 'step_count_mismatch') return 'Saved structured steps and mapping rows have different counts.'
  if (kind === 'generated_file_edited') return `Generated file has manual edits: ${detail || 'unknown file'}.`
  if (kind === 'generated_file_stale') return `Generated file is stale against newer source data: ${detail || 'unknown file'}.`
  if (kind === 'generated_file_conflict') return `Generated file has conflicting manual edits and source changes: ${detail || 'unknown file'}.`
  return detail ? `${kind}: ${detail}` : kind
}

function stepFromIssue(issue: string) {
  const match = issue.match(/step_(\d+)/)
  return match ? Number(match[1]) : undefined
}

function generatedFileFromIssue(kind: string, detail: string) {
  return kind.startsWith('generated_file_') && detail ? detail : undefined
}

function validationIssueTitle(issue: ValidationIssue) {
  if (issue.step) return `Step ${issue.step}`
  if (issue.file) return issue.file
  return issue.source === 'worker' ? 'Worker structure' : 'Flow'
}

function validationStatusClass(errorCount: number, warningCount: number, pending: boolean) {
  if (pending) return 'bg-slate-700 text-white'
  if (errorCount) return 'bg-red-700 text-white'
  if (warningCount) return 'bg-yellow-700 text-white'
  return 'bg-green-700 text-white'
}

function mappingApiFailureMessage(action: string, error: unknown) {
  const message = getApiErrorMessage(error, 'Mapping request failed.')
  return `${action}: ${message}`
}

function validationIssueClass(severity: ValidationIssue['severity']) {
  if (severity === 'error') return 'border-red-800 bg-red-950/30 text-red-200'
  if (severity === 'warning') return 'border-yellow-800 bg-yellow-950/30 text-yellow-200'
  return 'border-slate-800 bg-slate-900 text-slate-300'
}

function pascalName(value: string) {
  const words = value.split(/[^a-zA-Z0-9]+/).filter(Boolean)
  const name = words.map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()).join('')
  return name || 'Generated'
}

function latestRun(runs: WebwrightRun[], caseId: string | undefined) {
  if (!caseId) return undefined
  return runs
    .filter((candidate) => candidate.test_case_id === caseId)
    .sort((a, b) => {
      const left = Date.parse(a.started_at || a.ended_at || '')
      const right = Date.parse(b.started_at || b.ended_at || '')
      return (Number.isNaN(right) ? 0 : right) - (Number.isNaN(left) ? 0 : left)
    })[0]
}

function runTime(run: WebwrightRun) {
  if (!run.started_at) return 'No start time recorded'
  return new Date(run.started_at).toLocaleString()
}

function artifactPath(outputPath: string, fileName: string) {
  const separator = outputPath.includes('\\') ? '\\' : '/'
  return `${outputPath.replace(/[\\/]+$/, '')}${separator}${fileName}`
}
