import { useCallback, useState } from 'react'

import { ApiError, api, fieldErrors } from '../../lib/api'
import type { Paged } from './types'

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(fieldErrors(error)).flat()
    return details.length > 0 ? details.join(' ') : error.message
  }
  return 'Could not reach the server. Please try again.'
}

/** Every row of a paged list (bounded, because structure data is small). */
export async function fetchAll<T>(path: string, maxPages = 20): Promise<T[]> {
  const separator = path.includes('?') ? '&' : '?'
  const rows: T[] = []
  for (let page = 1; page <= maxPages; page++) {
    const url = page === 1 ? path : `${path}${separator}page=${page}`
    const body = await api<Paged<T>>(url)
    rows.push(...body.results)
    if (!body.next) break
  }
  return rows
}

/** Runs a change and keeps its outcome as a status or an error message for the screen. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async (work: () => Promise<string>) => {
    setBusy(true)
    setMessage(null)
    setError(null)
    try {
      setMessage(await work())
      return true
    } catch (caught) {
      setError(describeError(caught))
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  const clear = useCallback(() => {
    setMessage(null)
    setError(null)
  }, [])

  return { busy, message, error, run, clear }
}
