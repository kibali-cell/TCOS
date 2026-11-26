import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'

import { ApiError, fieldErrors } from '../../lib/api'
import { useAuth } from './useAuth'

export function LoginPage() {
  const { state, signIn, completeTwoFactor } = useAuth()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [secondStep, setSecondStep] = useState(false)
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)

  if (state.status === 'signed-in') {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from && from !== '/login' ? from : '/'} replace />
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await signIn(username.trim(), password)
      if (result === 'two-factor') {
        setPassword('')
        setSecondStep(true)
      }
    } catch (caught) {
      setPassword('')
      if (caught instanceof ApiError && caught.code === 'validation_error') {
        setError(Object.values(fieldErrors(caught))[0]?.[0] ?? 'Enter your username and password.')
      } else if (caught instanceof ApiError && caught.status !== 0) {
        setError(caught.message)
      } else {
        setError('Could not reach the server. Check your connection and try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  async function onSubmitCode(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await completeTwoFactor(code.trim(), useRecovery)
    } catch (caught) {
      setCode('')
      if (caught instanceof ApiError && caught.status === 429) {
        setError(caught.message)
      } else if (caught instanceof ApiError && caught.status === 401) {
        // Too long ago, or never started: back to the first step.
        setError(caught.message)
        if (/start again/i.test(caught.message)) setSecondStep(false)
      } else if (caught instanceof ApiError && caught.status !== 0) {
        setError(caught.message)
      } else {
        setError('Could not reach the server. Check your connection and try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (secondStep) {
    return (
      <main className="login-page">
        <div className="card login-card">
          <p className="login-brand">TCOS</p>
          <h1>Second step</h1>
          <p className="muted">
            {useRecovery
              ? 'Enter one of your recovery codes. Each works only once.'
              : 'Enter the 6-digit code from your authenticator app.'}
          </p>
          <form onSubmit={onSubmitCode} noValidate>
            <div className="field">
              <label htmlFor="two-factor-code">
                {useRecovery ? 'Recovery code' : 'Authenticator code'}
              </label>
              <input
                id="two-factor-code"
                name="code"
                autoComplete="one-time-code"
                inputMode={useRecovery ? 'text' : 'numeric'}
                autoCapitalize="none"
                spellCheck={false}
                required
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
            </div>
            {error && (
              <p role="alert" className="form-error">
                {error}
              </p>
            )}
            <button type="submit" className="button primary" disabled={busy || !code.trim()}>
              {busy ? 'Checking…' : 'Verify'}
            </button>
          </form>
          <p className="small">
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setUseRecovery((value) => !value)
                setCode('')
                setError(null)
              }}
            >
              {useRecovery ? 'Use the authenticator app instead' : 'Use a recovery code instead'}
            </button>
          </p>
          <p className="small">
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setSecondStep(false)
                setCode('')
                setError(null)
              }}
            >
              Start again
            </button>
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="login-page">
      <div className="card login-card">
        <p className="login-brand">TCOS</p>
        <h1>Sign in</h1>
        <p className="muted">Tuleeni Orphans Home</p>

        {state.status === 'anonymous' && state.sessionEnded && (
          <p className="notice" role="status">
            Your session has ended. Please sign in again.
          </p>
        )}

        <form onSubmit={onSubmit} noValidate>
          <div className="field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
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
            disabled={busy || !username || !password}
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="small">
          <Link to="/forgot-password">Forgot your password?</Link>
        </p>
      </div>
    </main>
  )
}
