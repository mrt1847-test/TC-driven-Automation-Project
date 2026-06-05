import { executionArtifactPath, executionRunDir, type ExecutionErrorGuide } from '@/lib/executionErrors'

type ExecutionRunErrorPanelProps = {
  guide: ExecutionErrorGuide
  resultPath?: string | null
  compact?: boolean
  onRetry?: () => void
  retryPending?: boolean
  onInstallDeps?: () => void
  installPending?: boolean
  onHealthCheck?: () => void
  healthPending?: boolean
  onRerunFailed?: () => void
  rerunPending?: boolean
  onOpenDiagnosis?: () => void
}

export function ExecutionRunErrorPanel({
  guide,
  resultPath,
  compact = false,
  onRetry,
  retryPending = false,
  onInstallDeps,
  installPending = false,
  onHealthCheck,
  healthPending = false,
  onRerunFailed,
  rerunPending = false,
  onOpenDiagnosis
}: ExecutionRunErrorPanelProps) {
  const runDir = executionRunDir(resultPath)
  const stderrPath = executionArtifactPath(resultPath, 'stderr.log')
  const stdoutPath = executionArtifactPath(resultPath, 'stdout.log')

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
        {guide.isBootstrapFailure && onInstallDeps && (
          <button
            type="button"
            className="rounded bg-yellow-700 px-2 py-1 text-xs text-white disabled:opacity-50"
            disabled={installPending}
            onClick={onInstallDeps}
          >
            {installPending ? 'Installing...' : 'Install Dependencies'}
          </button>
        )}
        {onHealthCheck && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200 disabled:opacity-50"
            disabled={healthPending}
            onClick={onHealthCheck}
          >
            {healthPending ? 'Checking...' : 'Health Check'}
          </button>
        )}
        {!guide.isBootstrapFailure && onRerunFailed && (
          <button
            type="button"
            className="rounded bg-yellow-700 px-2 py-1 text-xs text-white disabled:opacity-50"
            disabled={rerunPending}
            onClick={onRerunFailed}
          >
            {rerunPending ? 'Queueing...' : 'Rerun failed'}
          </button>
        )}
        {!guide.isBootstrapFailure && onOpenDiagnosis && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={onOpenDiagnosis}
          >
            Open Diagnosis
          </button>
        )}
        {onRetry && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200 disabled:opacity-50"
            disabled={retryPending}
            onClick={onRetry}
          >
            {retryPending ? 'Running...' : 'Retry run'}
          </button>
        )}
        {runDir && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={() => window.electronAPI?.openPath(runDir)}
          >
            Open run folder
          </button>
        )}
        {stderrPath && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={() => window.electronAPI?.openPath(stderrPath)}
          >
            Open stderr
          </button>
        )}
        {stdoutPath && (
          <button
            type="button"
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-200"
            onClick={() => window.electronAPI?.openPath(stdoutPath)}
          >
            Open stdout
          </button>
        )}
      </div>
    </div>
  )
}
