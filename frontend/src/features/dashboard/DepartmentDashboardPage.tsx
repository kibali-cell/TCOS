import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError, api } from '../../lib/api'
import { describeError } from '../approvals/describeError'
import { StatusBadge } from '../approvals/shared'
import { ActivityList } from './DashboardPage'
import type { DepartmentDashboardData } from './types'

export function DepartmentDashboardPage() {
  const { id } = useParams()
  const [data, setData] = useState<DepartmentDashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api<DepartmentDashboardData>(`/dashboard/departments/${id}/`)
      .then((result) => !cancelled && setData(result))
      .catch(
        (e) =>
          !cancelled &&
          setError(
            e instanceof ApiError && e.status === 404
              ? 'This department was not found, or you do not have access to it.'
              : describeError(e),
          ),
      )
    return () => {
      cancelled = true
    }
  }, [id])

  if (error)
    return (
      <p role="alert" className="form-error">
        {error}
      </p>
    )
  if (!data) return <p className="muted">Loading…</p>

  return (
    <>
      <h1>{data.department.name}</h1>
      <p className="muted">Head: {data.department.head ?? 'Not set'}</p>
      <div className="button-row no-print">
        <button type="button" className="button" onClick={() => window.print()}>
          Print
        </button>
      </div>
      <section className="figure-grid">
        <div className="card figure">
          <div className="muted">Staff</div>
          <div className="figure-value">{data.staff_count}</div>
          <div className="muted small">Counted from current staff assignments.</div>
        </div>
        {data.pending_approvals && (
          <div className="card figure">
            <div className="muted">Open requests</div>
            <div className="figure-value">{data.pending_approvals.count}</div>
          </div>
        )}
      </section>
      {data.pending_approvals && data.pending_approvals.latest.length > 0 && (
        <section className="card" aria-label="Open requests">
          <h2>Open requests</h2>
          <ul className="plain-list">
            {data.pending_approvals.latest.map((r) => (
              <li key={r.id}>
                <Link to={`/approvals/${r.id}`}>{r.request_number ?? 'Draft'}</Link> · {r.title} ·{' '}
                {r.requester} <StatusBadge status={r.status} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.recent_activity && (
        <section className="card" aria-label="Recent activity">
          <h2>Recent activity</h2>
          <ActivityList rows={data.recent_activity} />
        </section>
      )}
    </>
  )
}
