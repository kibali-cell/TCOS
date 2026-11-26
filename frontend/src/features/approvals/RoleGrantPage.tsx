import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../../lib/api'
import { PersonPicker } from '../organisation/PersonPicker'
import type { Person } from '../organisation/types'
import { describeError } from './describeError'
import type { RequestDetail } from './types'

interface RoleOption {
  id: string
  name: string
  is_active: boolean
  is_sensitive: boolean
  sensitive_reasons: string[]
}

export function RoleGrantPage() {
  const navigate = useNavigate()
  const [roles, setRoles] = useState<RoleOption[] | null>(null)
  const [person, setPerson] = useState<Person | null>(null)
  const [role, setRole] = useState('')
  const [validTo, setValidTo] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<{ results: RoleOption[] }>('/rbac/roles/')
      .then((data) => setRoles(data.results.filter((r) => r.is_active && r.is_sensitive)))
      .catch((e) => setError(describeError(e)))
  }, [])

  const chosen = roles?.find((r) => r.id === role)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!person) {
      setError('Choose the person who will receive the role.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const created = await api<RequestDetail>('/approvals/role-grants/', {
        method: 'POST',
        body: { user: person.id, role, reason, valid_to: validTo || null },
      })
      navigate(`/approvals/${created.id}`)
    } catch (e) {
      setError(describeError(e))
      setBusy(false)
    }
  }

  return (
    <>
      <p>
        <Link to="/approvals">← Approval Centre</Link>
      </p>
      <h1>Grant a sensitive role</h1>
      <p className="muted">
        Roles that reach child, medical, financial or staff records, or that can decide or export,
        are not given directly. A second person (the Executive Director or a Board Member) must
        approve first. You cannot request a role for yourself.
      </p>
      <form className="card" onSubmit={submit} aria-label="Grant a sensitive role">
        <PersonPicker label="Person" value={person} onChange={setPerson} />
        <div className="field">
          <label htmlFor="grant-role">Role</label>
          <select id="grant-role" value={role} onChange={(e) => setRole(e.target.value)} required>
            <option value="">Choose a role…</option>
            {roles?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        {chosen && (
          <ul className="muted small">
            {chosen.sensitive_reasons.map((reasonText) => (
              <li key={reasonText}>{reasonText}</li>
            ))}
          </ul>
        )}
        <div className="field">
          <label htmlFor="grant-until">Ends on (optional)</label>
          <input
            id="grant-until"
            type="date"
            value={validTo}
            onChange={(e) => setValidTo(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="grant-reason">Why does this person need it?</label>
          <textarea
            id="grant-reason"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
          />
        </div>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <button type="submit" className="button primary" disabled={busy}>
          Send for approval
        </button>
      </form>
    </>
  )
}
