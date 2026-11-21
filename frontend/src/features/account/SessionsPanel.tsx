import { useCallback, useEffect, useState } from 'react'

import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'

export interface DeviceSession {
  id: string
  device_label: string
  ip_address: string | null
  created_at: string
  last_seen_at: string
  is_current: boolean
}

/** The user's signed-in devices, with per-device sign out and "Sign out all other devices". */
export function SessionsPanel({ reloadKey = 0 }: { reloadKey?: number }) {
  const [sessions, setSessions] = useState<DeviceSession[] | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(
    () =>
      api<{ results: DeviceSession[] }>('/auth/sessions/')
        .then((data) => {
          setSessions(data.results)
          setLoadError(false)
        })
        .catch(() => setLoadError(true)),
    [],
  )

  useEffect(() => {
    void load()
  }, [load, reloadKey])

  async function run(action: () => Promise<string>) {
    setBusy(true)
    setMessage(null)
    setFailure(null)
    try {
      setMessage(await action())
    } catch {
      setFailure('That did not work. Please try again.')
    } finally {
      await load()
      setBusy(false)
    }
  }

  const others = sessions?.filter((item) => !item.is_current) ?? []

  return (
    <section className="card" aria-labelledby="devices-heading">
      <h2 id="devices-heading">Where you are signed in</h2>
      <p className="muted">
        If you lost a phone or used a shared computer, sign out the other devices. They are signed
        out immediately.
      </p>

      {loadError && (
        <p role="alert" className="form-error">
          Could not load your devices.
        </p>
      )}
      {sessions === null && !loadError && <p role="status">Loading…</p>}

      {sessions && (
        <ul className="device-list" aria-label="Signed-in devices">
          {sessions.map((item) => (
            <li key={item.id}>
              <div>
                <strong>{item.device_label}</strong>
                {item.is_current && <span className="badge">This device</span>}
                <div className="muted small">
                  Signed in {formatDateTime(item.created_at)} · Last active{' '}
                  {formatDateTime(item.last_seen_at)}
                  {item.ip_address ? ` · ${item.ip_address}` : ''}
                </div>
              </div>
              {!item.is_current && (
                <button
                  type="button"
                  className="button"
                  disabled={busy}
                  aria-label={`Sign out ${item.device_label}, last active ${formatDateTime(item.last_seen_at)}`}
                  onClick={() =>
                    run(async () => {
                      await api(`/auth/sessions/${item.id}/`, {
                        method: 'DELETE',
                      })
                      return 'That device was signed out.'
                    })
                  }
                >
                  Sign out
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        className="button danger"
        disabled={busy || others.length === 0}
        onClick={() =>
          run(async () => {
            const result = await api<{ ended: number }>('/auth/sessions/end-others/', {
              method: 'POST',
            })
            return result.ended === 1
              ? '1 other device was signed out.'
              : `${result.ended} other devices were signed out.`
          })
        }
      >
        Sign out all other devices
      </button>

      {message && (
        <p role="status" className="status-ok">
          {message}
        </p>
      )}
      {failure && (
        <p role="alert" className="form-error">
          {failure}
        </p>
      )}
    </section>
  )
}
