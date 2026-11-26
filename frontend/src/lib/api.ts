/**
 * Minimal API client for the TCOS backend.
 *
 * - Same-origin requests only; the browser sends the session cookie itself
 *   (HttpOnly, never readable by JavaScript). No tokens in localStorage.
 * - Unsafe methods carry Django's CSRF token from the `csrftoken` cookie.
 * - Errors are normalised from the backend envelope
 *   {"error": {"code", "message", "details"}} into ApiError.
 */

const API_PREFIX = '/api/v1'
const CSRF_COOKIE = 'csrftoken'
const CSRF_HEADER = 'X-CSRFToken'
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

/** Called when the server says the session is gone (401), except for failed sign-in attempts. */
let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

const SIGN_IN_PATH = '/auth/login/'

/** Field messages from a validation error, e.g. {"new_password": ["Too short."]}. */
export function fieldErrors(error: unknown): Record<string, string[]> {
  if (!(error instanceof ApiError) || typeof error.details !== 'object' || error.details === null) {
    return {}
  }
  const result: Record<string, string[]> = {}
  for (const [key, value] of Object.entries(error.details as Record<string, unknown>)) {
    if (Array.isArray(value)) result[key] = value.map(String)
  }
  return result
}

export function getCookie(name: string): string | null {
  const prefix = `${name}=`
  for (const part of document.cookie.split(';')) {
    const trimmed = part.trim()
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length))
    }
  }
  return null
}

async function ensureCsrfCookie(): Promise<string> {
  const existing = getCookie(CSRF_COOKIE)
  if (existing) return existing
  await fetch(`${API_PREFIX}/csrf/`, { credentials: 'same-origin' })
  const token = getCookie(CSRF_COOKIE)
  if (!token) {
    throw new ApiError(0, 'csrf_unavailable', 'Could not obtain a security token.')
  }
  return token
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (UNSAFE_METHODS.has(method)) {
    headers[CSRF_HEADER] = await ensureCsrfCookie()
  }

  let response: Response
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, 'network_error', 'Could not reach the server.')
  }

  if (response.status === 204) return undefined as T

  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    if (response.status === 401 && path !== SIGN_IN_PATH) unauthorizedHandler?.()
    const envelope = (payload as { error?: Record<string, unknown> } | null)?.error
    if (envelope && typeof envelope.code === 'string') {
      throw new ApiError(
        response.status,
        envelope.code,
        typeof envelope.message === 'string' ? envelope.message : 'The request failed.',
        envelope.details ?? null,
      )
    }
    throw new ApiError(response.status, 'error', 'The request failed.')
  }

  return payload as T
}

/** POST a JSON body and receive a file (for example a CSV export). */
export async function apiDownload(
  path: string,
  body: unknown,
): Promise<{ blob: Blob; filename: string }> {
  let response: Response
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      method: 'POST',
      headers: {
        Accept: 'text/csv, application/json',
        'Content-Type': 'application/json',
        [CSRF_HEADER]: await ensureCsrfCookie(),
      },
      credentials: 'same-origin',
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach the server.')
  }
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.()
    let payload: { error?: Record<string, unknown> } | null = null
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    const envelope = payload?.error
    throw new ApiError(
      response.status,
      typeof envelope?.code === 'string' ? envelope.code : 'error',
      typeof envelope?.message === 'string' ? envelope.message : 'The request failed.',
      envelope?.details ?? null,
    )
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^";]+)"?/.exec(disposition)
  return { blob: await response.blob(), filename: match?.[1] ?? 'audit-log.csv' }
}
