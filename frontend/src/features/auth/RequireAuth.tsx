import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './useAuth'

/** Protects routes. This is convenience only: the server enforces access on every request. */
export function RequireAuth() {
  const { state, refresh } = useAuth()
  const location = useLocation()

  if (state.status === 'loading') {
    return (
      <p className="centered-message" role="status">
        Loading…
      </p>
    )
  }

  if (state.status === 'unreachable') {
    return (
      <div className="centered-message">
        <p role="alert" className="status-error">
          Could not reach the server.
        </p>
        <button type="button" className="button" onClick={() => void refresh()}>
          Try again
        </button>
      </div>
    )
  }

  if (state.status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  const mustAct = state.user.must_change_password || state.twoFactor.setup_required
  if (mustAct && location.pathname !== '/account') {
    return <Navigate to="/account" replace />
  }

  return <Outlet />
}
