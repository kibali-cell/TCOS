import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { describeError } from './describeError'
import { tzs, type LimitsView, type Policy, type RequestDetail } from './types'

function PolicyCard({ policy, title }: { policy: Policy; title: string }) {
  return (
    <section className="card" aria-label={title}>
      <h2>
        {title} (version {policy.version_number})
      </h2>
      <p>
        {policy.is_ratified ? (
          <span className="badge">
            Ratified by {policy.ratified_by?.name} on {formatDateTime(policy.ratified_at)}
          </span>
        ) : (
          <span className="badge warn">Provisional: not yet ratified by the Board</span>
        )}
      </p>
      <ul className="plain-list">
        <li>Low risk: up to {tzs(policy.low_max)}</li>
        <li>
          Medium risk: above {tzs(policy.low_max)}, up to {tzs(policy.medium_max)}
        </li>
        <li>High risk: above {tzs(policy.medium_max)}</li>
        <li>
          Always high risk: {policy.always_high.length ? policy.always_high.join(', ') : 'none'}
        </li>
      </ul>
      {policy.reason && <p className="muted small">{policy.reason}</p>}
    </section>
  )
}

export function LimitsPage() {
  const navigate = useNavigate()
  const [view, setView] = useState<LimitsView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [low, setLow] = useState('')
  const [medium, setMedium] = useState('')
  const [always, setAlways] = useState<string[]>([])
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api<LimitsView>('/approvals/tzs-limits/')
      .then((data) => {
        setView(data)
        if (data.active) {
          setLow((v) => v || String(data.active!.low_max))
          setMedium((v) => v || String(data.active!.medium_max))
          setAlways((v) => (v.length ? v : data.active!.always_high))
        }
      })
      .catch((e) => setError(describeError(e)))
  }, [])
  useEffect(load, [load])

  async function propose(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await api<RequestDetail>('/approvals/tzs-limits/propose/', {
        method: 'POST',
        body: { low_max: Number(low), medium_max: Number(medium), always_high: always, reason },
      })
      navigate(`/approvals/${created.id}`)
    } catch (e) {
      setError(describeError(e))
      setBusy(false)
    }
  }

  if (error && !view)
    return (
      <p role="alert" className="form-error">
        {error}
      </p>
    )
  if (!view) return <p className="muted">Loading…</p>

  return (
    <>
      <p>
        <Link to="/approvals">← Approval Centre</Link>
      </p>
      <h1>TZS limits</h1>
      <p className="muted">{view.explanation}</p>
      {view.active && <PolicyCard policy={view.active} title="In force" />}
      {view.pending && (
        <>
          <PolicyCard policy={view.pending} title="Waiting for approval" />
          {view.pending.request_id && (
            <p>
              <Link to={`/approvals/${view.pending.request_id}`}>Open the approval request</Link>
            </p>
          )}
        </>
      )}
      {view.can_propose && !view.pending && (
        <form className="card" onSubmit={propose} aria-label="Propose new limits">
          <h2>Propose new limits</h2>
          <p className="muted small">
            Nothing changes until someone other than you approves. To ratify the current numbers as
            they are, propose them unchanged.
          </p>
          <div className="field">
            <label htmlFor="limit-low">Low risk up to (TZS)</label>
            <input
              id="limit-low"
              inputMode="numeric"
              value={low}
              onChange={(e) => setLow(e.target.value.replace(/[^0-9]/g, ''))}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="limit-medium">Medium risk up to (TZS)</label>
            <input
              id="limit-medium"
              inputMode="numeric"
              value={medium}
              onChange={(e) => setMedium(e.target.value.replace(/[^0-9]/g, ''))}
              required
            />
          </div>
          <fieldset className="field">
            <legend>Always high risk</legend>
            {view.kinds.map((kind) => (
              <label key={kind.code} className="check">
                <input
                  type="checkbox"
                  checked={always.includes(kind.code)}
                  onChange={(e) =>
                    setAlways(
                      e.target.checked
                        ? [...always, kind.code]
                        : always.filter((c) => c !== kind.code),
                    )
                  }
                />{' '}
                {kind.label}
              </label>
            ))}
          </fieldset>
          <div className="field">
            <label htmlFor="limit-reason">Reason</label>
            <textarea
              id="limit-reason"
              rows={2}
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
      )}
      <h2>Earlier versions</h2>
      <ul className="plain-list">
        {view.history.map((policy) => (
          <li key={policy.id}>
            Version {policy.version_number}: {policy.state_label} — low up to {tzs(policy.low_max)},
            medium up to {tzs(policy.medium_max)}
          </li>
        ))}
      </ul>
    </>
  )
}
