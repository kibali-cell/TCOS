import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { ApiError, api, apiDownload, fieldErrors } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { useCan } from '../auth/usePermissions'
import {
  NO_FILTERS,
  activeFilters,
  describeChange,
  humanise,
  type AuditDetail,
  type AuditPage,
  type Filters,
} from './types'

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(fieldErrors(error)).flat()
    return details.length > 0 ? details.join(' ') : error.message
  }
  return 'Something went wrong. Please try again.'
}

function EventDetails({ id }: { id: number }) {
  const [detail, setDetail] = useState<AuditDetail | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    api<AuditDetail>(`/audit/events/${id}/`)
      .then((data) => !cancelled && setDetail(data))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [id])

  if (failed)
    return (
      <p role="alert" className="form-error">
        Could not load the details.
      </p>
    )
  if (!detail) return <p className="muted">Loading details…</p>

  const changes = Object.entries(detail.changes)
  const metadata = Object.entries(detail.metadata)
  return (
    <div className="audit-detail">
      <h3>What changed</h3>
      {changes.length === 0 ? (
        <p className="muted">No field changes were recorded for this event.</p>
      ) : (
        <ul className="audit-changes">
          {changes.map(([field, value]) => (
            <li key={field}>
              <strong>{field}</strong>: {describeChange(value)}
            </li>
          ))}
        </ul>
      )}
      {metadata.length > 0 && (
        <>
          <h3>Other information</h3>
          <ul className="audit-changes">
            {metadata.map(([key, value]) => (
              <li key={key}>
                <strong>{key}</strong>: {describeChange(value)}
              </li>
            ))}
          </ul>
        </>
      )}
      <dl className="details">
        <dt>Request</dt>
        <dd>{detail.request_id || '—'}</dd>
        <dt>Address</dt>
        <dd>{detail.ip_address ?? '—'}</dd>
        <dt>Device</dt>
        <dd>{detail.user_agent || '—'}</dd>
        <dt>Integrity hash</dt>
        <dd className="mono">{detail.event_hash}</dd>
      </dl>
    </div>
  )
}

export function AuditLogPage() {
  const can = useCan()
  const canExport = can('audit', 'EXPORT')

  const [draft, setDraft] = useState<Filters>(NO_FILTERS)
  const [applied, setApplied] = useState<Filters>(NO_FILTERS)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<AuditPage | null>(null)
  const [types, setTypes] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    api<{ results: string[] }>('/audit/event-types/')
      .then((body) => setTypes(body.results))
      .catch(() => setTypes([]))
  }, [])

  const load = useCallback(() => {
    const params = new URLSearchParams(activeFilters(applied))
    if (page > 1) params.set('page', String(page))
    const query = params.toString()
    let cancelled = false
    api<AuditPage>(`/audit/events/${query ? `?${query}` : ''}`)
      .then((body) => {
        if (cancelled) return
        setData(body)
        setError(null)
      })
      .catch((caught) => {
        if (cancelled) return
        setData(null)
        setError(describe(caught))
      })
    return () => {
      cancelled = true
    }
  }, [applied, page])

  useEffect(() => load(), [load])

  const apply = (event: FormEvent) => {
    event.preventDefault()
    setOpen(null)
    setPage(1)
    setApplied(draft)
  }

  const clear = () => {
    setDraft(NO_FILTERS)
    setApplied(NO_FILTERS)
    setPage(1)
    setOpen(null)
  }

  async function exportCsv() {
    setExporting(true)
    setNotice(null)
    setError(null)
    try {
      const { blob, filename } = await apiDownload('/audit/export/', activeFilters(applied))
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      setNotice('Export downloaded. The export itself has been recorded in the audit log.')
      setPage(1)
    } catch (caught) {
      setError(describe(caught))
    } finally {
      setExporting(false)
    }
  }

  const set = (name: keyof Filters) => (event: { target: { value: string } }) =>
    setDraft((current) => ({ ...current, [name]: event.target.value }))

  return (
    <>
      <h1>Audit log</h1>
      <p className="muted">
        A permanent record of who did what and when. Entries cannot be edited or removed.
      </p>

      <form className="card audit-filters" onSubmit={apply} aria-label="Filter the audit log">
        <div className="field">
          <label htmlFor="audit-q">Search</label>
          <input id="audit-q" value={draft.q} onChange={set('q')} />
        </div>
        <div className="field">
          <label htmlFor="audit-type">Event type</label>
          <select id="audit-type" value={draft.event_type} onChange={set('event_type')}>
            <option value="">All events</option>
            {types.map((type) => (
              <option key={type} value={type}>
                {humanise(type)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="audit-success">Outcome</label>
          <select id="audit-success" value={draft.success} onChange={set('success')}>
            <option value="">Any outcome</option>
            <option value="true">Succeeded</option>
            <option value="false">Failed or refused</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="audit-object">Record type</label>
          <input id="audit-object" value={draft.object_type} onChange={set('object_type')} />
        </div>
        <div className="field">
          <label htmlFor="audit-from">From date</label>
          <input id="audit-from" type="date" value={draft.date_from} onChange={set('date_from')} />
        </div>
        <div className="field">
          <label htmlFor="audit-to">To date</label>
          <input id="audit-to" type="date" value={draft.date_to} onChange={set('date_to')} />
        </div>
        <div className="button-row audit-actions">
          <button type="submit" className="button primary">
            Apply filters
          </button>
          <button type="button" className="button" onClick={clear}>
            Clear
          </button>
          {canExport && (
            <button type="button" className="button" disabled={exporting} onClick={exportCsv}>
              {exporting ? 'Exporting…' : 'Export CSV'}
            </button>
          )}
        </div>
      </form>

      {notice && (
        <p role="status" className="muted">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {!data && !error && <p className="muted">Loading…</p>}

      {data && data.results.length === 0 && <p className="card">No events match these filters.</p>}

      {data && data.results.length > 0 && (
        <>
          <p className="muted" aria-live="polite">
            {data.count} {data.count === 1 ? 'event' : 'events'}
          </p>
          <table className="audit-table">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                <th scope="col">What</th>
                <th scope="col">Record</th>
                <th scope="col">Outcome</th>
                <th scope="col">
                  <span className="visually-hidden">Details</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((row) => (
                <FragmentRow
                  key={row.id}
                  row={row}
                  expanded={open === row.id}
                  onToggle={() => setOpen(open === row.id ? null : row.id)}
                />
              ))}
            </tbody>
          </table>
          <div className="button-row">
            <button
              type="button"
              className="button"
              disabled={!data.previous}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              Newer
            </button>
            <span className="muted">Page {page}</span>
            <button
              type="button"
              className="button"
              disabled={!data.next}
              onClick={() => setPage((value) => value + 1)}
            >
              Older
            </button>
          </div>
        </>
      )}
    </>
  )
}

function FragmentRow({
  row,
  expanded,
  onToggle,
}: {
  row: AuditPage['results'][number]
  expanded: boolean
  onToggle: () => void
}) {
  const record = [row.object_type, row.object_id].filter(Boolean).join(' ')
  return (
    <>
      <tr>
        <td data-label="When">{formatDateTime(row.occurred_at)}</td>
        <td data-label="Who">{row.actor_username || 'System'}</td>
        <td data-label="What">{humanise(row.event_type)}</td>
        <td data-label="Record">{record || '—'}</td>
        <td data-label="Outcome">
          <span className={row.success ? 'badge' : 'badge warn'}>
            {row.success ? 'Succeeded' : 'Failed'}
          </span>
        </td>
        <td className="audit-toggle">
          <button
            type="button"
            className="button"
            aria-expanded={expanded}
            aria-label={`${expanded ? 'Hide' : 'Show'} details of event ${row.id}`}
            onClick={onToggle}
          >
            {expanded ? 'Hide' : 'Details'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="audit-detail-row">
          <td colSpan={6}>
            <EventDetails id={row.id} />
          </td>
        </tr>
      )}
    </>
  )
}
