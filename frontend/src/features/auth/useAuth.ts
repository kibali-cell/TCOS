import { createContext, useContext } from 'react'

export interface User {
  id: string
  username: string
  full_name: string
  email: string
  phone: string
  status: string
  must_change_password: boolean
  last_login: string | null
}

export interface SessionInfo {
  idle_expires_at: string | null
  absolute_expires_at: string | null
}

/** {module: {ACTION: widest scope}}. For showing and hiding only; the server decides. */
export type Permissions = Record<string, Record<string, string>>

export interface RoleSummary {
  code: string
  name: string
  department: string | null
}

export interface AuthPayload {
  user: User
  session: SessionInfo
  permissions: Permissions
  roles: RoleSummary[]
}

export type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous'; sessionEnded: boolean }
  | { status: 'unreachable' }
  | {
      status: 'signed-in'
      user: User
      session: SessionInfo
      permissions: Permissions
      roles: RoleSummary[]
    }

export interface AuthContextValue {
  state: AuthState
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}

/** The signed-in user. Only call inside routes wrapped by RequireAuth. */
export function useCurrentUser(): User {
  const { state } = useAuth()
  if (state.status !== 'signed-in') throw new Error('No signed-in user')
  return state.user
}
