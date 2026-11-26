import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api } from '../../lib/api'

/** Always shows the same confirmation, whether or not the account exists. */
export function ForgotPasswordPage() {
  const [identifier, setIdentifier] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api<{ detail: string }>('/auth/password/forgot/', {
        method: 'POST',
        body: { identifier: identifier.trim() },
      })
      setMessage(result.detail)
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status !== 0
          ? caught.message
          : 'Could not reach the server. Check your connection and try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-page">
      <div className="card login-card">
        <p className="login-brand">TCOS</p>
        <h1>Forgot your password?</h1>
        {message ? (
          <>
            <p role="status" className="status-ok">
              {message}
            </p>
            <p className="small">
              <Link to="/login">Back to sign in</Link>
            </p>
          </>
        ) : (
          <>
            <p className="muted">
              Enter your username or e-mail address. If an account matches, we send a link to the
              e-mail address on record.
            </p>
            <form onSubmit={onSubmit} noValidate>
              <div className="field">
                <label htmlFor="identifier">Username or e-mail</label>
                <input
                  id="identifier"
                  name="identifier"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  required
                  value={identifier}
                  onChange={(event) => setIdentifier(event.target.value)}
                />
              </div>
              {error && (
                <p role="alert" className="form-error">
                  {error}
                </p>
              )}
              <button
                type="submit"
                className="button primary"
                disabled={busy || !identifier.trim()}
              >
                {busy ? 'Sending…' : 'Send reset link'}
              </button>
            </form>
            <p className="small">
              <Link to="/login">Back to sign in</Link>
            </p>
          </>
        )}
      </div>
    </main>
  )
}
