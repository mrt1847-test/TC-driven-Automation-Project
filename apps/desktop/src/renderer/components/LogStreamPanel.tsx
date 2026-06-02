import { useEffect, useRef } from 'react'

type LogStreamPanelProps = {
  logs: string[]
  onClear?: () => void
  title?: string
  emptyMessage?: string
  className?: string
  streaming?: boolean
  maxHeightClass?: string
}

export function LogStreamPanel({
  logs,
  onClear,
  title = 'Live Logs',
  emptyMessage = 'Logs will appear here...',
  className = '',
  streaming = false,
  maxHeightClass = 'max-h-96'
}: LogStreamPanelProps) {
  const scrollRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return
    element.scrollTop = element.scrollHeight
  }, [logs])

  return (
    <section className={`rounded border border-slate-800 bg-slate-900 ${className}`}>
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
          {streaming && <span className="text-xs text-green-400">Streaming</span>}
        </div>
        {onClear && (
          <button
            type="button"
            className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-100"
            onClick={onClear}
          >
            Clear
          </button>
        )}
      </div>
      <pre
        ref={scrollRef}
        className={`overflow-auto p-3 text-xs text-slate-300 ${maxHeightClass}`}
      >
        {logs.length ? logs.join('\n') : emptyMessage}
      </pre>
    </section>
  )
}
