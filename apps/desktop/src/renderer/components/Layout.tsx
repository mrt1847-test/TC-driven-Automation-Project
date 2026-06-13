import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { LogStreamPanel } from '@/components/LogStreamPanel'
import { useAutomationKeyDeepLink } from '@/lib/caseDeepLink'
import { useAppStore } from '@/store/appStore'

type WorkspaceId = 'generate-raw' | 'automation-ide'

const workspaces: {
  id: WorkspaceId
  label: string
  shortLabel: string
  defaultPath: string
  links: [string, string][]
}[] = [
  {
    id: 'generate-raw',
    label: 'Generate Raw',
    shortLabel: 'Raw',
    defaultPath: '/',
    links: [
      ['/', 'Dashboard'],
      ['/import', 'TC Import'],
      ['/cases', 'TC List'],
      ['/webwright', 'Webwright']
    ]
  },
  {
    id: 'automation-ide',
    label: 'Automation IDE',
    shortLabel: 'IDE',
    defaultPath: '/mapping',
    links: [
      ['/mapping', 'Mapping'],
      ['/ide', 'Project IDE'],
      ['/runner', 'Runner'],
      ['/results', 'Results'],
      ['/export', 'Export']
    ]
  }
]

function workspaceForPath(pathname: string): WorkspaceId {
  const automationPaths = workspaces.find((w) => w.id === 'automation-ide')!.links.map(([to]) => to)
  if (automationPaths.some((to) => to !== '/' && (pathname === to || pathname.startsWith(`${to}/`)))) {
    return 'automation-ide'
  }
  return 'generate-raw'
}

export function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  useAutomationKeyDeepLink()
  const currentProject = useAppStore((s) => s.currentProject)
  const selectedCase = useAppStore((s) => s.selectedCase)
  const logs = useAppStore((s) => s.logs)
  const clearLogs = useAppStore((s) => s.clearLogs)
  const activeWorkspace = workspaceForPath(location.pathname)
  const workspace = workspaces.find((w) => w.id === activeWorkspace)!
  const activeRoute = workspace.links.find(([to]) => (to === '/' ? location.pathname === '/' : location.pathname.startsWith(to)))?.[1]
    || (location.pathname === '/settings' ? 'Settings' : 'Workspace')
  const latestLogs = logs.slice(-6)
  const showFullLogs = ['/ide', '/webwright'].some((path) => location.pathname.startsWith(path))

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <aside className="w-16 bg-slate-950 border-r border-slate-800 py-3 flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => navigate('/')}
          className="h-9 w-9 rounded bg-slate-800 text-xs font-semibold text-white"
          title="TC Studio"
        >
          TC
        </button>

        <div className="mt-3 flex flex-col gap-2">
          {workspaces.map((w) => (
            <button
              key={w.id}
              type="button"
              onClick={() => navigate(w.id === activeWorkspace ? location.pathname : w.defaultPath)}
              title={w.label}
              className={`h-10 w-10 rounded text-xs font-semibold ${
                activeWorkspace === w.id && location.pathname !== '/settings'
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
              }`}
            >
              {w.shortLabel}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => navigate('/settings')}
          title="Settings"
          className={`mt-auto h-10 w-10 rounded text-xs font-semibold ${
            location.pathname === '/settings'
              ? 'bg-slate-700 text-white'
              : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
          }`}
        >
          Set
        </button>
      </aside>

      <aside className="w-56 bg-slate-900 border-r border-slate-800 p-4 flex flex-col gap-4">
        <div>
          <h1 className="text-base font-semibold">TC Studio</h1>
          <p className="mt-1 text-xs text-slate-400">{workspace.label}</p>
        </div>

        <nav className="flex flex-col gap-1 border-t border-slate-700 pt-3">
          {workspace.links.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm ${isActive ? 'bg-slate-800 text-white' : 'hover:bg-slate-800/70 text-slate-300'}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto pt-3 border-t border-slate-700">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `block px-3 py-2 rounded text-sm ${isActive ? 'bg-slate-800 text-white' : 'hover:bg-slate-800/70 text-slate-300'}`
            }
          >
            Settings
          </NavLink>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="h-12 border-b border-slate-800 bg-slate-950 px-4 flex items-center justify-between">
          <div className="min-w-0">
            <div className="text-sm font-medium">{activeRoute}</div>
            <div className="truncate text-xs text-slate-500">{currentProject?.name || 'No project selected'}</div>
          </div>
          <div className="text-xs text-slate-500">{workspace.label}</div>
        </header>

        <div className="flex min-h-0 flex-1">
          <main className="min-w-0 flex-1 overflow-auto p-6">
            <Outlet />
          </main>

          <aside className="w-64 border-l border-slate-800 bg-slate-950 p-4 text-sm">
            <h2 className="font-semibold">Context</h2>
            <dl className="mt-4 space-y-3 text-xs">
              <div>
                <dt className="text-slate-500">Project</dt>
                <dd className="mt-1 truncate text-slate-200">{currentProject?.name || 'None'}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Workspace</dt>
                <dd className="mt-1 text-slate-200">{workspace.label}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Surface</dt>
                <dd className="mt-1 text-slate-200">{activeRoute}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Selected TC</dt>
                <dd className="mt-1 truncate text-slate-200">
                  {selectedCase && selectedCase.project_id === currentProject?.id ? selectedCase.automation_key : 'None'}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">Log Lines</dt>
                <dd className="mt-1 text-slate-200">{logs.length}</dd>
              </div>
            </dl>
          </aside>
        </div>

        <section className={showFullLogs ? 'h-48 border-t border-slate-800 bg-slate-950' : 'h-32 border-t border-slate-800 bg-slate-950'}>
          {showFullLogs ? (
            <LogStreamPanel
              className="h-full rounded-none border-0 bg-slate-950"
              logs={logs}
              maxHeightClass="h-[calc(100%-2.25rem)]"
              onClear={clearLogs}
              title="Logs"
            />
          ) : (
            <>
              <div className="h-9 px-4 flex items-center justify-between border-b border-slate-800">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Logs</h2>
                <button
                  type="button"
                  onClick={clearLogs}
                  className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                >
                  Clear
                </button>
              </div>
              <pre className="h-[calc(100%-2.25rem)] overflow-auto px-4 py-2 text-xs text-slate-300">
                {latestLogs.length ? latestLogs.join('\n') : 'No logs yet.'}
              </pre>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
