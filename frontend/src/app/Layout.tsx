import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'

import { useAuth, useCurrentUser } from '../features/auth/useAuth'
import { MODULES } from './modules'

export function Layout() {
  const [open, setOpen] = useState(false)
  const user = useCurrentUser()
  const { signOut } = useAuth()

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  const close = () => setOpen(false)

  return (
    <div className="app">
      <aside id="sidebar" className={`sidebar${open ? ' open' : ''}`}>
        <div className="sidebar-brand">
          <span className="brand-mark">TCOS</span>
          <span className="brand-sub">Tuleeni Orphans Home</span>
        </div>
        <nav aria-label="Main navigation">
          <ul className="nav-list">
            <li>
              <NavLink to="/" end onClick={close}>
                Dashboard
              </NavLink>
            </li>
            {MODULES.map((module) => (
              <li key={module.slug}>
                <NavLink to={`/modules/${module.slug}`} onClick={close}>
                  {module.name}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      {open && <div className="overlay" data-testid="overlay" onClick={close} />}

      <div className="main">
        <header className="topbar">
          <button
            type="button"
            className="menu-button"
            aria-label={open ? 'Close navigation' : 'Open navigation'}
            aria-expanded={open}
            aria-controls="sidebar"
            onClick={() => setOpen((value) => !value)}
          >
            <span aria-hidden="true">☰</span>
          </button>
          <span className="topbar-title">Tuleeni Children Operating System</span>
          <div className="topbar-user">
            <Link to="/account" className="topbar-name">
              {user.full_name}
            </Link>
            <button type="button" className="button" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
