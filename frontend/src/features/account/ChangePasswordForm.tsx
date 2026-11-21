import { useState, type FormEvent } from 'react'

import { ApiError, api, fieldErrors } from '../../lib/api'

interface Props {
  forced: boolean
  onChanged: () => void
}

export function ChangePasswordForm({ forced, onChanged }: Props) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [general, setGeneral] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setErrors({})
    setGeneral(null)
    setDone(null)
    if (next !== confirm) {
      setErrors({ confirm: ['The two new passwords do not match.'] })
      return
    }
    setBusy(true)
    try {
      const result = await api<{ ended_other_sessions: number }>('/auth/password/change/', {
        method: 'POST',
        body: { current_password: current, new_password: next },
      })
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(
        result.ended_other_sessions > 0
          ? `Password changed. ${result.ended_other_sessions} other device(s) were signed out.`
          : 'Password changed.',
      )
      onChanged()
    } catch (caught) {
      const fields = fieldErrors(caught)
      if (Object.keys(fields).length > 0) setErrors(fields)
      else if (caught instanceof ApiError && caught.status !== 0) setGeneral(caught.message)
      else setGeneral('Could not reach the server.')
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
    <section className="card" aria-labelledby="password-heading">
      <h2 id="password-heading">Change password</h2>
      {forced && (
        <p className="notice" role="status">
          You must choose a new password before you can use the system.
        </p>
      )}
      <form onSubmit={onSubmit} noValidate>
        <div className="field">
          <label htmlFor="current_password">Current password</label>
          <input
            id="current_password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            aria-describedby={errors.current_password ? 'current_password-error' : undefined}
          />
          {fieldError('current_password')}
        </div>
        <div className="field">
          <label htmlFor="new_password">New password</label>
          <input
            id="new_password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
            aria-describedby={errors.new_password ? 'new_password-error' : 'password-hint'}
          />
          <p id="password-hint" className="muted small">
            At least 12 characters. Avoid common passwords and your own name or username.
          </p>
          {fieldError('new_password')}
        </div>
        <div className="field">
          <label htmlFor="confirm_password">Repeat new password</label>
          <input
            id="confirm_password"
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
            {general}
          </p>
        )}
        {done && (
          <p role="status" className="status-ok">
            {done}
          </p>
        )}
        <button
          type="submit"
          className="button primary"
          disabled={busy || !current || !next || !confirm}
        >
          {busy ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </section>
  )
}
