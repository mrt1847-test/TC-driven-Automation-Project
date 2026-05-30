import { NavLink, Outlet } from 'react-router-dom'

const links = [
  ['/', 'Dashboard'],
  ['/import', 'TC Import'],
  ['/cases', 'TC List'],
  ['/webwright', 'Webwright'],
  ['/mapping', 'Mapping'],
  ['/ide', 'Project IDE'],
  ['/runner', 'Runner'],
  ['/results', 'Results'],
  ['/export', 'Export'],
  ['/settings', 'Settings']
]

export function Layout() {
  return (
    <div className="flex h-screen">
      <aside className="w-56 bg-slate-900 border-r border-slate-700 p-4 flex flex-col gap-2">
        <h1 className="text-lg font-semibold mb-4">TC Studio</h1>
        {links.map(([to, label]) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `block px-3 py-2 rounded ${isActive ? 'bg-blue-600' : 'hover:bg-slate-800'}`
            }
          >
            {label}
          </NavLink>
        ))}
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
