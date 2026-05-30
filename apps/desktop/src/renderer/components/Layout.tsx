import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

type WorkspaceId = 'generate-raw' | 'automation-ide'

const workspaces: {
  id: WorkspaceId
  label: string
  defaultPath: string
  links: [string, string][]
}[] = [
  {
    id: 'generate-raw',
    label: 'Generate Raw',
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
  const activeWorkspace = workspaceForPath(location.pathname)
  const workspace = workspaces.find((w) => w.id === activeWorkspace)!

  return (
    <div className="flex h-screen">
      <aside className="w-60 bg-slate-900 border-r border-slate-700 p-4 flex flex-col gap-3">
        <h1 className="text-lg font-semibold">TC Studio</h1>

        <div className="flex flex-col gap-1">
          {workspaces.map((w) => (
            <button
              key={w.id}
              type="button"
              onClick={() => navigate(w.id === activeWorkspace ? location.pathname : w.defaultPath)}
              className={`text-left px-3 py-2 rounded text-sm font-medium ${
                activeWorkspace === w.id ? 'bg-blue-600 text-white' : 'hover:bg-slate-800 text-slate-300'
              }`}
            >
              {w.label}
            </button>
          ))}
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
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
