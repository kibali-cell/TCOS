import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { SystemStatus } from '../status/SystemStatus'
import { describeError } from '../approvals/describeError'
import type { ActivityRow, DashboardData, Figure } from './types'

export function FigureCard({ figure }: { figure: Figure }) {
  return (
    <div className="card figure" data-source={figure.source}>
      <div className="muted">{figure.label}</div>
      <div className="figure-value">{figure.value === null ? '—' : figure.value}</div>
      <div className={`badge${figure.source === 'live' ? '' : ' warn'}`}>{figure.source_label}</div>
      {figure.source === 'live' && figure.reference_value !== null && (
        <div className="muted small">
          The earlier reference figure was {figure.reference_value} (not verified).
        </div>
      )}
      {figure.note && <div className="muted small">{figure.note}</div>}
    </div>
  )
}

export function ActivityList({ rows }: { rows: ActivityRow[] }) {
  if (rows.length === 0) return <p className="muted">No activity yet.</p>
  return (
    <ul className="plain-list">
      {rows.map((row) => (
        <li key={row.id}>
          <strong>{row.event_type.replace(/_/g, ' ').toLowerCase()}</strong> by {row.actor}
          {!row.success && ' (failed)'} · {formatDateTime(row.occurred_at)}
        </li>
      ))}
    </ul>
  )
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api<DashboardData>('/dashboard/')
      .then((result) => !cancelled && setData(result))
      .catch((e) => !cancelled && setError(describeError(e)))
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      <h1>Dashboard</h1>
      <div className="button-row no-print">
        <button type="button" className="button" onClick={() => window.print()}>
          Print dashboard
        </button>
        {data?.department && (
          <Link className="button" to={`/departments/${data.department.id}/dashboard`}>
            {data.department.name} dashboard
          </Link>
        )}
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && (
        <>
          {data.figures.length > 0 && (
            <section aria-label="Institution figures" className="figure-grid">
              {data.figures.map((figure) => (
                <FigureCard key={figure.key} figure={figure} />
              ))}
            </section>
          )}
          {data.approvals && (
            <section className="card" aria-label="Approvals">
              <h2>Approvals</h2>
              <p>
                <strong>{data.approvals.waiting_for_me}</strong> waiting for your decision ·{' '}
                <strong>{data.approvals.open_in_my_scope}</strong> open in your area ·{' '}
                <strong>{data.approvals.mine_open}</strong> of your own requests open
              </p>
              <Link to="/approvals" className="no-print">
                Open the Approval Centre
              </Link>
            </section>
          )}
          {data.finance && (
            <section className="card" aria-label="Financial summary">
              <h2>Financial summary</h2>
              <p className="muted">{data.finance.note}</p>
            </section>
          )}
          <section className="card" aria-label="Notifications">
            <h2>Notifications</h2>
            {data.notifications.latest.length === 0 && <p className="muted">Nothing new.</p>}
            <ul className="plain-list">
              {data.notifications.latest.map((n) => (
                <li key={n.id}>
                  <strong>{n.title}</strong>
                  {n.body && <span className="muted"> · {n.body}</span>}
                </li>
              ))}
            </ul>
          </section>
          {data.recent_activity && (
            <section className="card" aria-label="Recent activity">
              <h2>Recent activity</h2>
              <ActivityList rows={data.recent_activity} />
            </section>
          )}
          {data.figures.length === 0 && !data.approvals && !data.finance && (
            <p className="muted">
              There are no institution figures for your role. Use the menu to reach your work.
            </p>
          )}
        </>
      )}
      <div className="no-print">
        <SystemStatus />
      </div>
    </>
  )
}
