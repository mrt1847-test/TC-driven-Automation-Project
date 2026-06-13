import { formatExportIssue, type ExportErrorGuide } from '@/lib/exportErrors'

type ExportErrorPanelProps = {
  guide: ExportErrorGuide
  compact?: boolean
  onRetryPreview?: () => void
  previewPending?: boolean
  onRetryExport?: () => void
  exportPending?: boolean
  onOpenSettings?: () => void
  onOpenResults?: () => void
  onOpenMapping?: (automationKey?: string) => void
}

export function ExportErrorPanel({
  guide,
  compact = false,
  onRetryPreview,
  previewPending = false,
  onRetryExport,
  exportPending = false,
  onOpenSettings,
  onOpenResults,
  onOpenMapping
}: ExportErrorPanelProps) {
  return (
    <div className={`rounded border border-amber-900/60 bg-amber-950/20 ${compact ? 'p-2' : 'p-3'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-amber-100">{guide.title}</div>
          <div className="mt-1 text-xs text-amber-200/90">{guide.summary}</div>
        </div>
        <span className="rounded bg-amber-900/50 px-2 py-1 text-[11px] uppercase tracking-wide text-amber-100">
          {guide.category}
        </span>
      </div>
      {!compact && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-100/90">
          {guide.actions.map((action) => <li key={action}>{action}</li>)}
        </ul>
      )}
      {compact && (
        <div className="mt-2 text-xs text-amber-100/90">{guide.actions[0]}</div>
      )}
      {guide.issues.length > 0 && (
        <div className="mt-3 space-y-1">
          <div className="text-[11px] uppercase tracking-wide text-amber-200/80">Failed items</div>
          <ul className="max-h-28 space-y-1 overflow-auto text-xs text-amber-100/90">
            {guide.issues.map((issue, index) => (
              <li key={`${issue.kind}-${issue.automationKey || index}`} className="flex items-center justify-between gap-2 rounded bg-amber-950/40 px-2 py-1">
                <span>{formatExportIssue(issue)}</span>
                {issue.automationKey && onOpenMapping && (
                  <button
                    type="button"
                    className="shrink-0 rounded bg-slate-800 px-2 py-0.5 text-[11px] text-slate-200"
                    onClick={() => onOpenMapping(issue.automationKey)}
                  >
                    Mapping
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {guide.preserveLocalResults && (
        <div className="mt-2 text-[11px] text-amber-200/70">Local results.json and execution history are preserved.</div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {onRetryPreview && (
          <button
            type="button"
            className="rounded bg-yellow-700 px-2 py-1 text-xs text-white disabled:opacity-50"
            disabled={previewPending}
            onClick={onRetryPreview}
          >
            {previewPending ? 'Previewing...' : 'Retry preview'}
          </button>
        )}
        {onRetryExport && (
          <button
            type="button"
            className="rounded bg-green-700 px-2 py-1 text-xs text-white disabled:opacity-50"
            disabled={exportPending}
            onClick={onRetryExport}
          >
            {exportPending ? 'Exporting...' : 'Retry export'}
          </button>
        )}
        {onOpenMapping && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={() => onOpenMapping()}
          >
            Open mapping
          </button>
        )}
        {onOpenResults && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={onOpenResults}
          >
            Open results.json
          </button>
        )}
        {onOpenSettings && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={onOpenSettings}
          >
            Open Settings
          </button>
        )}
      </div>
    </div>
  )
}
