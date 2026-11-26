import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { useCan } from '../auth/usePermissions'
import type { Paged } from '../organisation/types'
import { describeError } from './describeError'
import { RiskBadge, StatusBadge } from './shared'
import { STATUS_LABELS, tzs, type NotificationItem, type RequestSummary } from './types'

type Tab = 'mine' | 'pending' | 'all' | 'notifications'

function RequestTable({ rows, showWho }: { rows: RequestSummary[]; showWho: boolean }) {
  return (
    <table className="audit-table">
      <thead>
        <tr>
          <th>Number</th>
          <th>Request</th>
          {showWho && <th>Raised by</th>}
          <th>Status</th>
          <th>Risk</th>
          <th>Amount</th>
          <th>Waiting for</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td data-label="Number">{row.request_number ?? 'Not submitted'}</td>
            <td data-label="Request">
              <Link to={`/approvals/${row.id}`}>{row.title}</Link>
              <div className="muted small">{row.type_label}</div>
            </td>
            {showWho && <td data-label="Raised by">{row.requester?.name ?? '—'}</td>}
            <td data-label="Status">
              <StatusBadge status={row.status} />
            </td>
            <td data-label="Risk">
              {row.status === 'DRAFT' ? '—' : <RiskBadge risk={row.risk_level} />}
            </td>
            <td data-label="Amount">{tzs(row.amount_tzs)}</td>
            <td data-label="Waiting for">
              {row.waiting_for.length > 0 ? row.waiting_for.map((p) => p.name).join(', ') : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Notifications() {
  const [items, setItems] = useState<NotificationItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api<Paged<NotificationItem>>('/approvals/notifications/')
      .then((page) => setItems(page.results))
      .catch((e) => setError(describeError(e)))
  }, [])
  useEffect(load, [load])

  async function markRead() {
    await api('/approvals/notifications/', { method: 'POST', body: {} })
    load()
  }

  if (error)
    return (
      <p role="alert" className="form-error">
        {error}
      </p>
    )
  if (!items) return <p className="muted">Loading…</p>
  if (items.length === 0) return <p className="card">You have no notifications.</p>
  return (
    <>
      <div className="button-row">
        <button type="button" className="button" onClick={() => void markRead()}>
          Mark all as read
        </button>
      </div>
      <ul className="plain-list">
        {items.map((item) => (
          <li key={item.id} className="card">
            <strong>{item.title}</strong>
            {!item.is_read && <span className="badge"> New</span>}
            <div className="muted small">
              {formatDateTime(item.created_at)}
              {item.body ? ` — ${item.body}` : ''}
            </div>
            {item.request_id && <Link to={`/approvals/${item.request_id}`}>Open the request</Link>}
          </li>
        ))}
      </ul>
    </>
  )
}

export function ApprovalsPage() {
  const can = useCan()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'mine'
  const status = params.get('status') ?? ''
  const search = params.get('search') ?? ''
  const [rows, setRows] = useState<RequestSummary[] | null>(null)
  const [count, setCount] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const listed = tab !== 'notifications'
  useEffect(() => {
    if (!listed) return
    let cancelled = false
    const query = new URLSearchParams({ view: tab })
    if (status) query.set('status', status)
    if (search) query.set('search', search)
    api<Paged<RequestSummary>>(`/approvals/requests/?${query.toString()}`)
      .then((page) => {
        if (cancelled) return
        setRows(page.results)
        setCount(page.count)
        setError(null)
      })
      .catch((e) => !cancelled && setError(describeError(e)))
    return () => {
      cancelled = true
    }
  }, [tab, status, search, listed])

  function choose(next: Tab) {
    setRows(null)
    setParams({ tab: next })
  }

  const tabs: [Tab, string][] = [
    ['mine', 'My requests'],
    ['pending', 'Pending my approval'],
    ...(can('approvals', 'VIEW') ? ([['all', 'All requests']] as [Tab, string][]) : []),
    ['notifications', 'Notifications'],
  ]

  return (
    <>
      <h1>Approval Centre</h1>
      <p className="muted">
        Requests are decided by someone other than the person who raised them. Nobody can approve
        their own request.
      </p>
      <div className="button-row">
        {can('approvals', 'CREATE') && (
          <Link to="/approvals/new" className="button primary">
            New request
          </Link>
        )}
        {can('users', 'MANAGE_USERS') && (
          <Link to="/approvals/role-grant" className="button">
            Grant a sensitive role
          </Link>
        )}
        <Link to="/approvals/limits" className="button">
          TZS limits
        </Link>
      </div>
      <div role="tablist" aria-label="Approval lists" className="button-row">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`button${tab === key ? ' primary' : ''}`}
            onClick={() => choose(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'notifications' && <Notifications />}
      {listed && (
        <>
          <div className="card audit-filters">
            <div className="field">
              <label htmlFor="approval-search">Search</label>
              <input
                id="approval-search"
                value={search}
                placeholder="Title, number or name"
                onChange={(e) => setParams({ tab, status, search: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="approval-status">Status</label>
              <select
                id="approval-status"
                value={status}
                onChange={(e) => setParams({ tab, search, status: e.target.value })}
              >
                <option value="">Any status</option>
                {Object.entries(STATUS_LABELS).map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          {!rows && !error && <p className="muted">Loading…</p>}
          {rows && rows.length === 0 && (
            <p className="card">
              {tab === 'pending' ? 'Nothing is waiting for your decision.' : 'No requests to show.'}
            </p>
          )}
          {rows && rows.length > 0 && (
            <>
              <p className="muted" aria-live="polite">
                {count} {count === 1 ? 'request' : 'requests'}
              </p>
              <RequestTable rows={rows} showWho={tab !== 'mine'} />
            </>
          )}
        </>
      )}
    </>
  )
}
