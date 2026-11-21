import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiError, api, setUnauthorizedHandler } from '../../lib/api'
import { AuthContext, type AuthPayload, type AuthState } from './useAuth'

/**
 * Holds who is signed in. The only source is the server (`/auth/me/`); nothing about
 * the user is kept in browser storage. A 401 from any request returns to the sign-in page.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })

  const refresh = useCallback(async () => {
    try {
      const payload = await api<AuthPayload>('/auth/me/')
      setState({
        status: 'signed-in',
        user: payload.user,
        session: payload.session,
      })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setState({ status: 'anonymous', sessionEnded: false })
      } else {
        setState({ status: 'unreachable' })
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    api<AuthPayload>('/auth/me/')
      .then((payload) => {
        if (!cancelled)
          setState({
            status: 'signed-in',
            user: payload.user,
            session: payload.session,
          })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setState(
          error instanceof ApiError && error.status === 401
            ? { status: 'anonymous', sessionEnded: false }
            : { status: 'unreachable' },
        )
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() =>
      setState((current) =>
        current.status === 'signed-in'
          ? { status: 'anonymous', sessionEnded: true }
          : { status: 'anonymous', sessionEnded: false },
      ),
    )
    return () => setUnauthorizedHandler(null)
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    const payload = await api<AuthPayload>('/auth/login/', {
      method: 'POST',
      body: { username, password },
    })
    setState({
      status: 'signed-in',
      user: payload.user,
      session: payload.session,
    })
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api('/auth/logout/', { method: 'POST' })
    } catch {
      // The session may already be gone; either way this browser is now signed out.
    }
    setState({ status: 'anonymous', sessionEnded: false })
  }, [])

  const value = useMemo(
    () => ({ state, signIn, signOut, refresh }),
    [state, signIn, signOut, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
