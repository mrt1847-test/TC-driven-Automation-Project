type FileListSectionProps = {
  emptyLabel: string
  files?: string[]
  title: string
  tone?: 'default' | 'amber' | 'green' | 'red'
}

function toneClass(tone: FileListSectionProps['tone']) {
  if (tone === 'amber') return 'text-amber-200'
  if (tone === 'green') return 'text-emerald-200'
  if (tone === 'red') return 'text-red-300'
  return 'text-slate-300'
}

function FileListSection({ emptyLabel, files, title, tone = 'default' }: FileListSectionProps) {
  const items = files || []
  return (
    <div>
      <div className={`text-[11px] font-medium uppercase tracking-wide ${toneClass(tone)}`}>{title}</div>
      {items.length ? (
        <ul className="mt-1 max-h-28 space-y-0.5 overflow-auto text-xs text-slate-400">
          {items.map((file) => (
            <li key={file} className="font-mono">{file}</li>
          ))}
        </ul>
      ) : (
        <div className="mt-1 text-xs text-slate-500">{emptyLabel}</div>
      )}
    </div>
  )
}

export type MaintenanceImpactSummary = {
  actionLabel: string
  affectedFiles?: string[]
  changedFiles?: string[]
  conflictFiles?: string[]
  editedFiles?: string[]
  staleFiles?: string[]
  note?: string
  preservedFiles?: string[]
  removedFiles?: string[]
  status?: string
  unaffectedCaseCount?: number
  updatedFiles?: string[]
  guidance?: string[]
}

export function MaintenanceImpactReview({
  onApply,
  onDismiss,
  pending,
  summary
}: {
  onApply: () => void
  onDismiss: () => void
  pending?: boolean
  summary: MaintenanceImpactSummary
}) {
  const hasConflict = Boolean(
    summary.conflictFiles?.length ||
    summary.editedFiles?.length ||
    summary.status === 'conflict'
  )
  const canApply = !hasConflict && summary.status !== 'conflict'

  return (
    <div className="space-y-3 rounded border border-slate-700 bg-slate-950 p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium text-slate-100">Maintenance impact review</div>
          <div className="mt-1 text-slate-400">{summary.actionLabel}</div>
          {summary.note && <div className="mt-1 text-slate-500">{summary.note}</div>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="rounded bg-slate-700 px-3 py-1.5 text-xs disabled:opacity-50"
            disabled={pending}
            type="button"
            onClick={onDismiss}
          >
            Dismiss
          </button>
          <button
            className="rounded bg-blue-700 px-3 py-1.5 text-xs disabled:opacity-50"
            disabled={pending || !canApply}
            type="button"
            onClick={onApply}
          >
            {pending ? 'Applying...' : 'Apply'}
          </button>
        </div>
      </div>
      {hasConflict && (
        <div className="rounded border border-red-900/60 bg-red-950/30 p-2 text-red-200">
          <div>Conflicts or manually edited generated files block this action.</div>
          {summary.guidance?.length ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-red-100/90">
              {summary.guidance.map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : (
            <div className="mt-1 text-red-100/90">
              Open the listed files in the IDE, reconcile manual edits, then preview or retry generation.
            </div>
          )}
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <FileListSection
          files={summary.affectedFiles}
          title="Affected files"
          emptyLabel="No generated files are in scope."
        />
        <FileListSection
          files={summary.preservedFiles}
          title="Preserved files"
          emptyLabel="No preserved files were identified."
          tone="green"
        />
        <FileListSection
          files={summary.changedFiles || summary.updatedFiles}
          title="Changed / updated files"
          emptyLabel="No file content changes are expected."
        />
        <FileListSection
          files={summary.removedFiles}
          title="Removed files"
          emptyLabel="No files will be deleted."
          tone="amber"
        />
        {summary.editedFiles?.length ? (
          <FileListSection
            files={summary.editedFiles}
            title="Edited files"
            emptyLabel="No edited files."
            tone="amber"
          />
        ) : null}
        {summary.staleFiles?.length ? (
          <FileListSection
            files={summary.staleFiles}
            title="Stale files"
            emptyLabel="No stale files."
            tone="amber"
          />
        ) : null}
        {summary.conflictFiles?.length ? (
          <FileListSection
            files={summary.conflictFiles}
            title="Conflict files"
            emptyLabel="No conflicts."
            tone="red"
          />
        ) : null}
      </div>
      {typeof summary.unaffectedCaseCount === 'number' && (
        <div className="text-slate-500">
          {summary.unaffectedCaseCount} other active case(s) remain unaffected.
        </div>
      )}
    </div>
  )
}

export function maintenanceSummaryFromRetirePreview(payload: {
  action?: string
  automationKey?: string
  cleanup?: Record<string, unknown>
  note?: string
}): MaintenanceImpactSummary {
  const cleanup = (payload.cleanup || payload) as Record<string, unknown>
  return {
    actionLabel: `${payload.action || cleanup.action || 'retire'} cleanup for ${payload.automationKey || cleanup.automationKey || 'selected case'}`,
    status: String(cleanup.status || ''),
    affectedFiles: (cleanup.affectedFiles as string[]) || [],
    changedFiles: (cleanup.updatedFiles as string[]) || [],
    removedFiles: (cleanup.removedFiles as string[]) || [],
    preservedFiles: (cleanup.preservedFiles as string[]) || [],
    conflictFiles: (cleanup.conflictFiles as string[]) || [],
    unaffectedCaseCount: Array.isArray(cleanup.unaffectedCaseIds) ? cleanup.unaffectedCaseIds.length : undefined,
    note: payload.note
  }
}

export function maintenanceSummaryFromRefreshPreview(payload: {
  automationKey?: string
  generation?: Record<string, unknown>
  note?: string
}): MaintenanceImpactSummary {
  const generation = payload.generation || {}
  return {
    actionLabel: `Raw refresh + regenerate for ${payload.automationKey || 'selected case'}`,
    status: (
      (generation.conflictFiles as string[])?.length ||
      (generation.editedFiles as string[])?.length
    ) ? 'conflict' : 'preview',
    affectedFiles: (generation.affectedFiles as string[]) || [],
    changedFiles: (generation.changedFiles as string[]) || [],
    preservedFiles: (generation.preservedFiles as string[]) || [],
    editedFiles: (generation.editedFiles as string[]) || [],
    staleFiles: (generation.staleFiles as string[]) || [],
    conflictFiles: (generation.conflictFiles as string[]) || [],
    note: payload.note
  }
}
