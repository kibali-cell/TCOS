import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { describeError } from '../approvals/describeError'
import { useCan } from '../auth/usePermissions'
import { STATUS_LABELS, type UserRow } from './types'

interface RoleOption {
  id: string
  name: string
  is_active: boolean
  is_sensitive: boolean
  sensitive_reasons: string[]
}

export function UserDetailPage() {
  const { id } = useParams()
  const can = useCan()
  const manage = can('users', 'MANAGE_USERS')
  const [user, setUser] = useState<UserRow | null>(null)
  const [roles, setRoles] = useState<RoleOption[]>([])
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [temporary, setTemporary] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ full_name: '', email: '', phone: '' })
  const [roleId, setRoleId] = useState('')
  const [reason, setReason] = useState('')

  const load = useCallback(() => {
    api<UserRow>(`/users/${id}/`)
      .then((data) => {
        setUser(data)
        setForm({ full_name: data.full_name, email: data.email, phone: data.phone })
        setError(null)
      })
      .catch((e) => setError(describeError(e)))
  }, [id])
  useEffect(load, [load])
  useEffect(() => {
    api<{ results: RoleOption[] }>('/rbac/roles/')
      .then((data) => setRoles(data.results.filter((r) => r.is_active)))
      .catch(() => undefined) // the role list only fills a drop-down
  }, [])

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await action()
      setMessage(done)
      load()
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  function save(event: FormEvent) {
    event.preventDefault()
    void run(() => api(`/users/${id}/`, { method: 'PATCH', body: form }), 'Saved.')
  }

  function setStatus(status: string) {
    void run(
      () => api(`/users/${id}/status/`, { method: 'POST', body: { status, reason } }),
      status === 'ACTIVE'
        ? 'Account activated.'
        : 'Account deactivated; their sessions have ended.',
    )
  }

  async function resetPassword() {
    setTemporary(null)
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const result = await api<{ temporary_password: string }>(`/users/${id}/temporary-password/`, {
        method: 'POST',
        body: {},
      })
      setTemporary(result.temporary_password)
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  if (!user) {
    return error ? (
      <p role="alert" className="form-error">
        {error}
      </p>
    ) : (
      <p className="muted">Loading…</p>
    )
  }

  const held = new Set(user.roles.map((r) => r.role_id))
  const plain = roles.filter((r) => !r.is_sensitive && !held.has(r.id))
  const sensitive = roles.filter((r) => r.is_sensitive && !held.has(r.id))

  return (
    <>
      <p>
        <Link to="/administration/users">← All users</Link>
      </p>
      <h1>{user.full_name}</h1>
      <p className="muted">
        {user.username} ·{' '}
        <span className={`badge${user.status === 'ACTIVE' ? '' : ' warn'}`}>
          {STATUS_LABELS[user.status] ?? user.status}
        </span>{' '}
        · Last sign-in {formatDateTime(user.last_login)}
      </p>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {temporary && (
        <div className="notice" role="status">
          Temporary password (shown only now, to be given privately; they must change it at first
          sign-in): <code className="mono">{temporary}</code>
        </div>
      )}

      <div className="card">
        <h2>Work</h2>
        <p>
          Department: {user.department?.name ?? 'None'} · Main post: {user.position ?? 'None'}
        </p>
        <p className="muted small">
          These follow the person&apos;s main post and are changed in{' '}
          <Link to="/administration/organisation">Organisation</Link>.
        </p>
      </div>

      <form className="card" onSubmit={save} aria-label="Details">
        <h2>Details</h2>
        <div className="field">
          <label htmlFor="ud-name">Full name</label>
          <input
            id="ud-name"
            value={form.full_name}
            disabled={!manage}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="ud-email">Email</label>
          <input
            id="ud-email"
            type="email"
            value={form.email}
            disabled={!manage}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="ud-phone">Phone</label>
          <input
            id="ud-phone"
            value={form.phone}
            disabled={!manage}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
        </div>
        {manage && (
          <button type="submit" className="button primary" disabled={busy}>
            Save details
          </button>
        )}
      </form>

      <div className="card">
        <h2>Roles</h2>
        {user.roles.length === 0 && <p>No roles.</p>}
        <ul>
          {user.roles.map((r) => (
            <li key={r.id}>
              {r.name}
              {r.department ? ` (${r.department} only)` : ''}{' '}
              {manage && (
                <button
                  type="button"
                  className="button"
                  disabled={busy}
                  aria-label={`Remove ${r.name}`}
                  onClick={() =>
                    void run(
                      () => api(`/rbac/users/${id}/roles/${r.id}/`, { method: 'DELETE' }),
                      `${r.name} removed.`,
                    )
                  }
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
        {manage && (
          <>
            <div className="field">
              <label htmlFor="ud-role">Give a role</label>
              <select id="ud-role" value={roleId} onChange={(e) => setRoleId(e.target.value)}>
                <option value="">Choose a role…</option>
                {plain.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              className="button"
              disabled={busy || !roleId}
              onClick={() =>
                void run(
                  () => api(`/rbac/users/${id}/roles/`, { method: 'POST', body: { role: roleId } }),
                  'Role given.',
                ).then(() => setRoleId(''))
              }
            >
              Give role
            </button>
            {sensitive.length > 0 && (
              <p className="muted small">
                Sensitive roles ({sensitive.map((r) => r.name).join(', ')}) need a second
                person&apos;s approval: use{' '}
                <Link to="/approvals/role-grant">Grant a sensitive role</Link>.
              </p>
            )}
          </>
        )}
      </div>

      {manage && (
        <div className="card">
          <h2>Account</h2>
          <div className="field">
            <label htmlFor="ud-reason">Reason (optional, kept in the audit log)</label>
            <input id="ud-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="button-row">
            {user.status === 'ACTIVE' ? (
              <button
                type="button"
                className="button danger"
                disabled={busy}
                onClick={() => setStatus('INACTIVE')}
              >
                Deactivate account
              </button>
            ) : (
              <button
                type="button"
                className="button primary"
                disabled={busy}
                onClick={() => setStatus('ACTIVE')}
              >
                Activate account
              </button>
            )}
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() =>
                void run(
                  () => api(`/users/${id}/unlock/`, { method: 'POST', body: {} }),
                  'Sign-in lockout cleared.',
                )
              }
            >
              Clear sign-in lockout
            </button>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void resetPassword()}
            >
              Set a temporary password
            </button>
          </div>
          <p className="muted small">
            Accounts are never deleted. A temporary password cannot be set for yourself or for
            anyone holding a sensitive role.
          </p>
        </div>
      )}
    </>
  )
}
