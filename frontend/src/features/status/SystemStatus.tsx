import { useEffect, useState } from 'react'

import { ApiError, api } from '../../lib/api'

type State =
  | { kind: 'loading' }
  | { kind: 'ok' }
  | { kind: 'database-unavailable' }
  | { kind: 'unreachable' }

interface Health {
  status: string
  database: string
}

/** Live backend and database status, read from /api/v1/health/. */
export function SystemStatus() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()

    api<Health>('/health/', { signal: controller.signal })
      .then((health) => {
        setState(health.status === 'ok' ? { kind: 'ok' } : { kind: 'database-unavailable' })
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        // The health endpoint answers 503 when the server is up but the database is not.
        if (error instanceof ApiError && error.status === 503) {
          setState({ kind: 'database-unavailable' })
        } else {
          setState({ kind: 'unreachable' })
        }
      })

    return () => controller.abort()
  }, [])

  return (
    <section className="card" aria-labelledby="system-status-title">
      <h2 id="system-status-title">System status</h2>
      {state.kind === 'loading' && <p>Checking…</p>}
      {state.kind === 'ok' && (
        <p className="status-ok" role="status">
          Server and database are reachable.
        </p>
      )}
      {state.kind === 'database-unavailable' && (
        <p className="status-error" role="alert">
          The server is running but the database is unavailable.
        </p>
      )}
      {state.kind === 'unreachable' && (
        <p className="status-error" role="alert">
          The server could not be reached.
        </p>
      )}
    </section>
  )
}
