import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { FileAttachments } from '../../components/FileAttachments'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { describeError } from './describeError'
import { RiskBadge, StatusBadge } from './shared'
import { ACTION_LABELS, tzs, type RequestDetail } from './types'

type Decision = 'approve' | 'reject' | 'review' | 'cancel' | 'comment' | 'submit'

function payloadLines(request: RequestDetail): string[] {
  const p = request.payload
  if (request.request_type === 'ROLE_GRANT') {
    const lines = [`Person: ${String(p.person)}`, `Role: ${String(p.role)}`]
    if (p.valid_from) lines.push(`From: ${String(p.valid_from)}`)
    if (p.valid_to) lines.push(`Until: ${String(p.valid_to)}`)
    const why = (p.why_sensitive as string[] | undefined) ?? []
    if (why.length > 0) lines.push(`Why this needs approval: ${why.join('; ')}`)
    return lines
  }
  if (request.request_type === 'TZS_LIMITS_CHANGE') {
    return [
      `Low risk up to ${tzs(p.low_max as number)}`,
      `Medium risk up to ${tzs(p.medium_max as number)}; high above that`,
      `Always high: ${((p.always_high as string[]) ?? []).join(', ') || 'none'}`,
    ]
  }
  return p.kind_label ? [`Kind: ${String(p.kind_label)}`] : []
}

export function RequestDetailPage() {
  const { id } = useParams()
  const [request, setRequest] = useState<RequestDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [comment, setComment] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api<RequestDetail>(`/approvals/requests/${id}/`)
      .then((data) => {
        setRequest(data)
        setError(null)
      })
      .catch((e) => setError(describeError(e)))
  }, [id])
  useEffect(load, [load])

  async function act(action: Decision) {
    setBusy(true)
    setError(null)
    try {
      const body: Record<string, string> = { comment }
      if ((action === 'approve' || action === 'reject') && request?.needs_password) {
        body.password = password
      }
      const updated = await api<RequestDetail>(`/approvals/requests/${id}/${action}/`, {
        method: 'POST',
        body,
      })
      setRequest(updated)
      setComment('')
      setPassword('')
    } catch (e) {
      setError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  if (error && !request)
    return (
      <p role="alert" className="form-error">
        {error}
      </p>
    )
  if (!request) return <p className="muted">Loading…</p>

  const can = request.can
  const deciding = can.approve || can.reject
  const lines = payloadLines(request)

  return (
    <>
      <p>
        <Link to="/approvals">← Approval Centre</Link>
      </p>
      <h1>{request.title}</h1>
      <p>
        <strong>{request.request_number ?? 'Not submitted yet'}</strong> · {request.type_label} ·{' '}
        <StatusBadge status={request.status} />{' '}
        {request.status !== 'DRAFT' && <RiskBadge risk={request.risk_level} />}
      </p>
      <dl className="details">
        <dt>Raised by</dt>
        <dd>{request.requester?.name ?? '—'}</dd>
        <dt>Department</dt>
        <dd>{request.department?.name ?? '—'}</dd>
        <dt>Amount</dt>
        <dd>{tzs(request.amount_tzs)}</dd>
        <dt>Submitted</dt>
        <dd>{formatDateTime(request.submitted_at)}</dd>
        {request.decided_at && (
          <>
            <dt>Decided</dt>
            <dd>{formatDateTime(request.decided_at)}</dd>
          </>
        )}
        {request.waiting_for.length > 0 && (
          <>
            <dt>Waiting for</dt>
            <dd>{request.waiting_for.map((p) => p.name).join(', ')}</dd>
          </>
        )}
      </dl>
      {request.description && <p className="card pre-wrap">{request.description}</p>}
      {lines.length > 0 && (
        <ul className="card plain-list">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {request.decision_comment && (
        <p className="notice">
          <strong>Decision note:</strong> {request.decision_comment}
        </p>
      )}

      <FileAttachments
        parentType="approvals.ApprovalRequest"
        parentId={request.id}
        files={request.attachments}
        canAttach={request.can_attach_files}
        onChange={load}
      />

      {request.route.length > 0 && (
        <>
          <h2>Approval route</h2>
          <ol className="route">
            {request.route.map((step) => (
              <li key={step.order} aria-current={step.state === 'current' ? 'step' : undefined}>
                <strong>{step.label}</strong> — {step.state}
                {step.escalated_to && (
                  <span className="muted small"> (escalated to {step.escalated_to})</span>
                )}
              </li>
            ))}
          </ol>
        </>
      )}

      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}

      {(deciding || can.cancel || can.comment || can.submit) && (
        <div className="card">
          <h2>Actions</h2>
          {(deciding || can.comment || can.cancel) && (
            <div className="field">
              <label htmlFor="req-comment">
                {can.reject ? 'Comment (required to reject)' : 'Comment'}
              </label>
              <textarea
                id="req-comment"
                rows={3}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </div>
          )}
          {deciding && request.needs_password && (
            <div className="field">
              <label htmlFor="req-password">Your password (high-risk decision)</label>
              <input
                id="req-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          )}
          <div className="button-row">
            {can.submit && (
              <button
                type="button"
                className="button primary"
                disabled={busy}
                onClick={() => void act('submit')}
              >
                Submit for approval
              </button>
            )}
            {can.review && (
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => void act('review')}
              >
                Start review
              </button>
            )}
            {can.approve && (
              <button
                type="button"
                className="button primary"
                disabled={busy}
                onClick={() => void act('approve')}
              >
                Approve
              </button>
            )}
            {can.reject && (
              <button
                type="button"
                className="button danger"
                disabled={busy}
                onClick={() => void act('reject')}
              >
                Reject
              </button>
            )}
            {can.comment && (
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => void act('comment')}
              >
                Add comment
              </button>
            )}
            {can.cancel && (
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => void act('cancel')}
              >
                Cancel request
              </button>
            )}
          </div>
        </div>
      )}

      <h2>History</h2>
      <ol className="route" aria-label="History">
        {request.history.map((entry) => (
          <li key={entry.id}>
            <strong>{ACTION_LABELS[entry.action] ?? entry.action}</strong> by{' '}
            {entry.actor?.name ?? 'the system'} · {formatDateTime(entry.at)}
            {entry.comment && <div className="muted pre-wrap">{entry.comment}</div>}
          </li>
        ))}
      </ol>
      <p className="muted small">History cannot be changed or removed.</p>
    </>
  )
}
