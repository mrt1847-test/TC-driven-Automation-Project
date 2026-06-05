import { describeWebwrightRunError, webwrightArtifactPath } from '@/lib/webwrightErrors'
import type { WebwrightRun } from '@/lib/api'

type WebwrightRunErrorPanelProps = {
  run: WebwrightRun
  compact?: boolean
  onRetry?: () => void
  retryPending?: boolean
}

export function WebwrightRunErrorPanel({
  run,
  compact = false,
  onRetry,
  retryPending = false
}: WebwrightRunErrorPanelProps) {
  if (!run.error_message && run.status !== 'failed') return null

  const guide = describeWebwrightRunError(run.error_message)

  return (
    <div className={`rounded border border-red-900/60 bg-red-950/20 ${compact ? 'p-2' : 'p-3'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-red-100">{guide.title}</div>
          <div className="mt-1 text-xs text-red-200/90">{guide.summary}</div>
        </div>
        <span className="rounded bg-red-900/50 px-2 py-1 text-[11px] uppercase tracking-wide text-red-100">
          {guide.category}
        </span>
      </div>
      {!compact && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-red-100/90">
          {guide.actions.map((action) => <li key={action}>{action}</li>)}
        </ul>
      )}
      {compact && (
        <div className="mt-2 text-xs text-red-100/90">{guide.actions[0]}</div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {onRetry && (
          <button
            type="button"
            className="rounded bg-yellow-700 px-2 py-1 text-xs text-white disabled:opacity-50"
            disabled={retryPending}
            onClick={onRetry}
          >
            {retryPending ? 'Retrying...' : 'Retry run'}
          </button>
        )}
        {run.output_path && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={() => window.electronAPI?.openPath(run.output_path!)}
          >
            Open run folder
          </button>
        )}
        {run.output_path && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={() => window.electronAPI?.openPath(webwrightArtifactPath(run.output_path!, 'stderr.log'))}
          >
            Open stderr
          </button>
        )}
      </div>
    </div>
  )
}
