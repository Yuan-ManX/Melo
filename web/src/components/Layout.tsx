import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { to: '/', label: '对话', color: 'var(--accent-2)' },
  { to: '/studio', label: '工作室', color: 'var(--accent)' },
  { to: '/voices', label: '声音库', color: 'var(--c-blue)' },
  { to: '/agents', label: 'Agent', color: 'var(--c-mint)' },
  { to: '/settings', label: '设置', color: 'var(--c-yellow)' },
]

export function Layout() {
  return (
    <div className="flex h-screen flex-col">
      <nav className="flex items-center gap-6 border-b border-[var(--border)] bg-[var(--bg-soft)]/70 px-6 py-3 backdrop-blur">
        <div className="flex items-center gap-2">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold text-white"
            style={{
              background: 'linear-gradient(135deg, var(--accent), var(--accent-2))',
              boxShadow: 'var(--shadow-glow)',
            }}
          >
            M
          </span>
          <span
            className="bg-clip-text text-lg font-bold text-transparent"
            style={{ backgroundImage: 'linear-gradient(135deg, var(--accent-2), var(--accent))' }}
          >
            Melo
          </span>
        </div>
        <div className="flex gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              style={({ isActive }) =>
                isActive
                  ? {
                      color: item.color,
                      backgroundColor: `color-mix(in srgb, ${item.color} 18%, transparent)`,
                    }
                  : undefined
              }
              className={({ isActive }) =>
                `rounded-full px-3.5 py-1.5 text-sm transition-all ${
                  isActive
                    ? 'font-medium'
                    : 'text-[var(--muted)] hover:bg-[var(--card)] hover:text-[var(--fg)]'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
