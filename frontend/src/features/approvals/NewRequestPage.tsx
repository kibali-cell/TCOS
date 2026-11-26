import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../../lib/api'
import { describeError } from './describeError'
import type { RequestDetail } from './types'

const KINDS = [
  ['', 'None of these'],
  ['PAYROLL', 'Payroll'],
  ['STAFF_LOAN', 'Staff loan'],
  ['PAYEE_CHANGE', 'Bank or payee change'],
  ['ASSET_DISPOSAL', 'Asset disposal'],
  ['WRITE_OFF', 'Write-off'],
  ['DONOR_REFUND', 'Donor refund'],
]

export function NewRequestPage() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const [kind, setKind] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save(event: FormEvent, submit: boolean) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const draft = await api<RequestDetail>('/approvals/requests/', {
        method: 'POST',
        body: {
          title,
          description,
          kind,
          amount_tzs: amount.trim() === '' ? null : Number(amount),
        },
      })
      if (submit) {
        await api<RequestDetail>(`/approvals/requests/${draft.id}/submit/`, {
          method: 'POST',
          body: {},
        })
      }
      navigate(`/approvals/${draft.id}`)
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
      <h1>New request</h1>
      <form className="card" onSubmit={(e) => void save(e, true)} aria-label="New request">
        <div className="field">
          <label htmlFor="req-title">Title</label>
          <input id="req-title" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="req-description">Details</label>
          <textarea
            id="req-description"
            rows={5}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="req-amount">Amount in TZS (if money is involved)</label>
          <input
            id="req-amount"
            inputMode="numeric"
            value={amount}
            onChange={(e) => setAmount(e.target.value.replace(/[^0-9]/g, ''))}
          />
        </div>
        <div className="field">
          <label htmlFor="req-kind">Kind of request</label>
          <select id="req-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <p className="muted small">
          The risk level and the approvers are set by the system, not by you. Money-related kinds
          are always high risk.
        </p>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="button-row">
          <button type="submit" className="button primary" disabled={busy}>
            Submit for approval
          </button>
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={(e) => void save(e, false)}
          >
            Save as draft
          </button>
        </div>
      </form>
    </>
  )
}
