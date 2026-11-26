import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { ApiError, api, fieldErrors } from '../../lib/api'
import { useAuth, type TwoFactorStatus } from '../auth/useAuth'

interface Enrolment {
  secret: string
  otpauth_uri: string
  qr: string
}

function describe(caught: unknown): string {
  if (caught instanceof ApiError && caught.status !== 0) {
    const fields = fieldErrors(caught)
    return Object.values(fields)[0]?.[0] ?? caught.message
  }
  return 'Could not reach the server.'
}

export function TwoFactorPanel() {
  const { refresh } = useAuth()
  const [status, setStatus] = useState<TwoFactorStatus | null>(null)
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [password, setPassword] = useState('')
  const [reauthCode, setReauthCode] = useState('')
  const [mode, setMode] = useState<'idle' | 'disable' | 'renew'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setStatus(await api<TwoFactorStatus>('/auth/2fa/'))
    } catch (caught) {
      setError(describe(caught))
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    api<TwoFactorStatus>('/auth/2fa/')
      .then((data) => {
        if (!cancelled) setStatus(data)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(describe(caught))
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(describe(caught))
    } finally {
      setBusy(false)
    }
  }

  const start = () =>
    run(async () => {
      setEnrolment(await api<Enrolment>('/auth/2fa/enrol/', { method: 'POST' }))
      setCode('')
    })

  const confirm = (event: FormEvent) => {
    event.preventDefault()
    return run(async () => {
      const result = await api<{ recovery_codes: string[] }>('/auth/2fa/confirm/', {
        method: 'POST',
        body: { code: code.trim() },
      })
      setCodes(result.recovery_codes)
      setEnrolment(null)
      setCode('')
      await load()
      await refresh()
    })
  }

  const reauth = (event: FormEvent) => {
    event.preventDefault()
    return run(async () => {
      const path = mode === 'disable' ? '/auth/2fa/disable/' : '/auth/2fa/recovery-codes/'
      const result = await api<{ recovery_codes?: string[] }>(path, {
        method: 'POST',
        body: { password, code: reauthCode.trim() },
      })
      if (result.recovery_codes) setCodes(result.recovery_codes)
      setPassword('')
      setReauthCode('')
      setMode('idle')
      await load()
      await refresh()
    })
  }

  return (
    <section className="card" aria-labelledby="twofactor-heading">
      <h2 id="twofactor-heading">Two-factor sign-in</h2>

      {status?.setup_required && !enrolment && !codes && (
        <p className="notice" role="status">
          Two-factor sign-in is required for your account or role. Set it up before you can use the
          rest of the system.
        </p>
      )}

      {codes && (
        <div role="status">
          <p>
            <strong>Save these recovery codes now.</strong> Each works once if you lose your phone.
            They will not be shown again.
          </p>
          <ul className="recovery-codes" aria-label="Recovery codes">
            {codes.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <button type="button" className="button" onClick={() => setCodes(null)}>
            I have saved them
          </button>
        </div>
      )}

      {status && !status.enabled && !enrolment && !codes && (
        <>
          <p className="muted">
            Add a second step at sign-in: a 6-digit code from an authenticator app on your phone.
          </p>
          <button
            type="button"
            className="button primary"
            disabled={busy}
            onClick={() => void start()}
          >
            Set up two-factor sign-in
          </button>
        </>
      )}

      {enrolment && (
        <form onSubmit={(event) => void confirm(event)} noValidate>
          <ol>
            <li>Open an authenticator app and scan this picture.</li>
          </ol>
          <div className="qr-box">
            <img src={enrolment.qr} alt="QR code for your authenticator app" />
          </div>
          <p className="small muted">
            Cannot scan? Enter this key by hand: <code className="mono">{enrolment.secret}</code>
          </p>
          <div className="field">
            <label htmlFor="enrol-code">Enter the 6-digit code it shows</label>
            <input
              id="enrol-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
          </div>
          <button type="submit" className="button primary" disabled={busy || !code.trim()}>
            Turn on
          </button>{' '}
          <button type="button" className="button" onClick={() => setEnrolment(null)}>
            Cancel
          </button>
        </form>
      )}

      {status?.enabled && mode === 'idle' && !codes && (
        <>
          <p role="status" className="status-ok">
            Two-factor sign-in is on. {status.recovery_codes_left} recovery code(s) left.
          </p>
          <button type="button" className="button" onClick={() => setMode('renew')}>
            New recovery codes
          </button>{' '}
          {!status.required && (
            <button type="button" className="button" onClick={() => setMode('disable')}>
              Turn off
            </button>
          )}
          {status.required && (
            <p className="muted small">
              Required for your account or role, so it cannot be turned off.
            </p>
          )}
        </>
      )}

      {mode !== 'idle' && (
        <form onSubmit={(event) => void reauth(event)} noValidate>
          <p className="muted">
            {mode === 'disable'
              ? 'To turn it off'
              : 'To get new recovery codes (the old ones stop working)'}
            , confirm it is you.
          </p>
          <div className="field">
            <label htmlFor="reauth-password">Your password</label>
            <input
              id="reauth-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="reauth-code">Current code (or a recovery code)</label>
            <input
              id="reauth-code"
              autoComplete="one-time-code"
              value={reauthCode}
              onChange={(event) => setReauthCode(event.target.value)}
            />
          </div>
          <button
            type="submit"
            className="button primary"
            disabled={busy || !password || !reauthCode.trim()}
          >
            {mode === 'disable' ? 'Turn off' : 'Get new codes'}
          </button>{' '}
          <button type="button" className="button" onClick={() => setMode('idle')}>
            Cancel
          </button>
        </form>
      )}

      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
    </section>
  )
}
