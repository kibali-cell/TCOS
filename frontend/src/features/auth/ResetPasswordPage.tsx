import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, api, fieldErrors } from '../../lib/api'

/**
 * The reset token travels in the URL fragment (`#token=...`), which browsers never send to the
 * server or in Referer headers. It is read once, then removed from the address bar.
 */
export function ResetPasswordPage() {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token'))
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [general, setGeneral] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (window.location.hash) {
      window.history.replaceState(null, '', window.location.pathname)
    }
  }, [])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setErrors({})
    setGeneral(null)
    if (next !== confirm) {
      setErrors({ confirm: ['The two passwords do not match.'] })
      return
    }
    setBusy(true)
    try {
      await api('/auth/password/reset/', {
        method: 'POST',
        body: { token, new_password: next },
      })
      setNext('')
      setConfirm('')
      setDone(true)
    } catch (caught) {
      const fields = fieldErrors(caught)
      if (fields.new_password) setErrors({ new_password: fields.new_password })
      else if (caught instanceof ApiError && caught.status !== 0) {
        setGeneral(fields.token?.[0] ?? caught.message)
      } else setGeneral('Could not reach the server. Check your connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  const fieldError = (name: string) =>
    errors[name]?.map((text) => (
      <p key={text} className="form-error" id={`${name}-error`}>
        {text}
      </p>
    ))

  return (
    <main className="login-page">
      <div className="card login-card">
        <p className="login-brand">TCOS</p>
        <h1>Choose a new password</h1>
        {done ? (
          <>
            <p role="status" className="status-ok">
              Your password has been changed. You were signed out everywhere.
            </p>
            <p>
              <Link className="button primary" to="/login">
                Sign in
              </Link>
            </p>
          </>
        ) : !token ? (
          <>
            <p role="alert" className="form-error">
              This link is not complete. Open the link from your e-mail again, or ask for a new one.
            </p>
            <p className="small">
              <Link to="/forgot-password">Send me a new link</Link>
            </p>
          </>
        ) : (
          <form onSubmit={onSubmit} noValidate>
            <div className="field">
              <label htmlFor="reset_new_password">New password</label>
              <input
                id="reset_new_password"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
                aria-describedby={errors.new_password ? 'new_password-error' : 'reset-hint'}
              />
              <p id="reset-hint" className="muted small">
                At least 12 characters. Avoid common passwords and your own name or username.
              </p>
              {fieldError('new_password')}
            </div>
            <div className="field">
              <label htmlFor="reset_confirm_password">Repeat new password</label>
              <input
                id="reset_confirm_password"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                aria-describedby={errors.confirm ? 'confirm-error' : undefined}
              />
              {fieldError('confirm')}
            </div>
            {general && (
              <p role="alert" className="form-error">
                {general} <Link to="/forgot-password">Ask for a new link</Link>
              </p>
            )}
            <button type="submit" className="button primary" disabled={busy || !next || !confirm}>
              {busy ? 'Saving…' : 'Set new password'}
            </button>
          </form>
        )}
      </div>
    </main>
  )
}
