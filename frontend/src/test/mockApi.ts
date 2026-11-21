import { vi } from 'vitest'

export interface MockReply {
  status?: number
  body?: unknown
}
type Handler = MockReply | ((request: { body: unknown; headers: Headers }) => MockReply)

export interface RecordedCall {
  method: string
  path: string
  body: unknown
  headers: Headers
}

export const USER = {
  id: '6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11',
  username: 'alice',
  full_name: 'Alice Mwangi',
  email: 'alice@example.org',
  phone: '',
  status: 'ACTIVE',
  must_change_password: false,
  last_login: '2026-11-19T20:00:00Z',
}

export const SESSION = {
  idle_expires_at: '2026-11-20T04:30:00Z',
  absolute_expires_at: '2026-11-20T15:00:00Z',
}

const MODULE_CODES = [
  'administration',
  'social_welfare',
  'children',
  'education',
  'medical',
  'finance',
  'projects',
  'hr',
  'procurement',
  'stores',
  'donors',
  'reports',
]

/** Everything visible and manageable, so tests that are not about permissions see every screen. */
export const FULL_ACCESS = {
  ...Object.fromEntries(MODULE_CODES.map((code) => [code, { VIEW: 'ALL' }])),
  users: { VIEW: 'ALL', MANAGE_USERS: 'ALL' },
}

export function meAs(permissions: Record<string, Record<string, string>>, roles = ROLES) {
  return { status: 200, body: { user: USER, session: SESSION, permissions, roles } }
}

export const ROLES: { code: string; name: string; department: string | null }[] = [
  { code: 'ADMINISTRATOR', name: 'Administrator', department: null },
]

export const ME = meAs(FULL_ACCESS)
export const NOT_SIGNED_IN = {
  status: 401,
  body: {
    error: {
      code: 'not_authenticated',
      message: 'Sign in required.',
      details: null,
    },
  },
}

/**
 * Replaces fetch with a table of handlers keyed by "METHOD /path" (path without /api/v1).
 * Unknown requests fail the test loudly instead of silently returning nothing.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: RecordedCall[] = []
  document.cookie = 'csrftoken=test-token; path=/'

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace(/^\/api\/v1/, '')
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    const headers = new Headers(init?.headers)
    calls.push({ method, path, body, headers })

    const handler = routes[`${method} ${path}`]
    if (!handler) throw new Error(`Unexpected request: ${method} ${path}`)
    const reply = typeof handler === 'function' ? handler({ body, headers }) : handler
    const status = reply.status ?? 200
    if (status === 204) return new Response(null, { status })
    return new Response(JSON.stringify(reply.body ?? {}), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export function apiError(status: number, code: string, message: string, details: unknown = null) {
  return { status, body: { error: { code, message, details } } }
}
