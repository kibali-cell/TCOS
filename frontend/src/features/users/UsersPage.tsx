import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { describeError } from '../approvals/describeError'
import { useCan } from '../auth/usePermissions'
import type { Paged } from '../organisation/types'
import { STATUS_LABELS, type UserRow } from './types'

const SORTS: [string, string][] = [
  ['full_name', 'Name'],
  ['username', 'Username'],
  ['created_at', 'Date created'],
  ['last_login', 'Last sign-in'],
  ['status', 'Status'],
]

function CreateUser({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState({ username: '', full_name: '', email: '', phone: '' })
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<{ name: string; password: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user = await api<UserRow & { temporary_password: string }>('/users/', {
        method: 'POST',
        body: form,
      })
      setCreated({ name: user.full_name, password: user.temporary_password })
      setForm({ username: '', full_name: '', email: '', phone: '' })
      onCreated()
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2>New user</h2>
      {created && (
        <div className="notice" role="status">
          <strong>{created.name} has been created.</strong> Give them this temporary password
          privately. It is shown only now and must be changed at first sign-in:{' '}
          <code className="mono">{created.password}</code>
        </div>
      )}
      <form onSubmit={submit} aria-label="New user">
        <div className="field">
          <label htmlFor="nu-name">Full name</label>
          <input
            id="nu-name"
            required
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="nu-username">Username</label>
          <input
            id="nu-username"
            required
            autoCapitalize="none"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="nu-email">Email</label>
          <input
            id="nu-email"
            type="email"
            required
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="nu-phone">Phone (optional)</label>
          <input
            id="nu-phone"
            inputMode="tel"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
        </div>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <button type="submit" className="button primary" disabled={busy}>
          Create user
        </button>
      </form>
      <p className="muted small">
        Roles and the department are given afterwards: sensitive roles through the Approval Centre,
        and the department through the person&apos;s main post in Organisation.
      </p>
    </div>
  )
}

export function UsersPage() {
  const can = useCan()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const status = params.get('status') ?? ''
  const ordering = params.get('ordering') ?? 'full_name'
  const page = Number(params.get('page') ?? '1') || 1
  const [rows, setRows] = useState<UserRow[] | null>(null)
  const [count, setCount] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    let cancelled = false
    const query = new URLSearchParams({ ordering, page: String(page) })
    if (q) query.set('q', q)
    if (status) query.set('status', status)
    api<Paged<UserRow>>(`/users/?${query.toString()}`)
      .then((result) => {
        if (cancelled) return
        setRows(result.results)
        setCount(result.count)
        setError(null)
      })
      .catch((e) => !cancelled && setError(describeError(e)))
    return () => {
      cancelled = true
    }
  }, [q, status, ordering, page, reload])

  function change(next: Record<string, string>) {
    const merged = { q, status, ordering, ...next }
    setParams(Object.fromEntries(Object.entries(merged).filter(([, v]) => v)))
  }

  const pages = Math.max(1, Math.ceil(count / 25))
  const descending = ordering.startsWith('-')

  return (
    <>
      <h1>Users</h1>
      <p className="muted no-print">
        Accounts are never deleted: a person who leaves is made inactive, which ends their sessions
        at once.
      </p>
      <div className="button-row no-print">
        {can('users', 'MANAGE_USERS') && (
          <button type="button" className="button primary" onClick={() => setAdding(!adding)}>
            {adding ? 'Close' : 'New user'}
          </button>
        )}
        <button type="button" className="button" onClick={() => window.print()}>
          Print this list
        </button>
      </div>
      {adding && can('users', 'MANAGE_USERS') && (
        <CreateUser onCreated={() => setReload((n) => n + 1)} />
      )}
      <div className="card audit-filters no-print">
        <div className="field">
          <label htmlFor="user-search">Search</label>
          <input
            id="user-search"
            value={q}
            placeholder="Name, username or email"
            onChange={(e) => change({ q: e.target.value, page: '' })}
          />
        </div>
        <div className="field">
          <label htmlFor="user-status">Status</label>
          <select
            id="user-status"
            value={status}
            onChange={(e) => change({ status: e.target.value, page: '' })}
          >
            <option value="">Any status</option>
            {Object.entries(STATUS_LABELS).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="user-sort">Sort by</label>
          <select
            id="user-sort"
            value={ordering.replace(/^-/, '')}
            onChange={(e) => change({ ordering: (descending ? '-' : '') + e.target.value })}
          >
            {SORTS.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="user-direction">Order</label>
          <select
            id="user-direction"
            value={descending ? 'desc' : 'asc'}
            onChange={(e) =>
              change({
                ordering: (e.target.value === 'desc' ? '-' : '') + ordering.replace(/^-/, ''),
              })
            }
          >
            <option value="asc">A to Z, oldest first</option>
            <option value="desc">Z to A, newest first</option>
          </select>
        </div>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {!rows && !error && <p className="muted">Loading…</p>}
      {rows && rows.length === 0 && <p className="card">No users match.</p>}
      {rows && rows.length > 0 && (
        <>
          <p className="muted" aria-live="polite">
            {count} {count === 1 ? 'user' : 'users'}
          </p>
          <table className="audit-table" aria-label="Users">
            <thead>
              <tr>
                <th>Name</th>
                <th>Username</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Department</th>
                <th>Position</th>
                <th>Roles</th>
                <th>Status</th>
                <th>Created</th>
                <th>Last sign-in</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td data-label="Name">
                    <Link to={`/administration/users/${row.id}`}>{row.full_name}</Link>
                  </td>
                  <td data-label="Username">{row.username}</td>
                  <td data-label="Email">{row.email}</td>
                  <td data-label="Phone">{row.phone || '—'}</td>
                  <td data-label="Department">{row.department?.name ?? '—'}</td>
                  <td data-label="Position">{row.position ?? '—'}</td>
                  <td data-label="Roles">
                    {row.roles.length ? row.roles.map((r) => r.name).join(', ') : 'None'}
                  </td>
                  <td data-label="Status">
                    <span className={`badge${row.status === 'ACTIVE' ? '' : ' warn'}`}>
                      {STATUS_LABELS[row.status] ?? row.status}
                    </span>
                  </td>
                  <td data-label="Created">{formatDateTime(row.created_at)}</td>
                  <td data-label="Last sign-in">{formatDateTime(row.last_login)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="button-row no-print">
            <button
              type="button"
              className="button"
              disabled={page <= 1}
              onClick={() => change({ page: String(page - 1) })}
            >
              Previous
            </button>
            <span className="muted" aria-live="polite">
              Page {page} of {pages}
            </span>
            <button
              type="button"
              className="button"
              disabled={page >= pages}
              onClick={() => change({ page: String(page + 1) })}
            >
              Next
            </button>
          </div>
        </>
      )}
    </>
  )
}
