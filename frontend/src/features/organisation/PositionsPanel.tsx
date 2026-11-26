import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { api } from '../../lib/api'
import { useCan } from '../auth/usePermissions'
import { describeError, fetchAll, useAction } from './shared'
import type { Department, Position } from './types'

const POSITIONS = '/organisation/positions/?archived=all&page_size=100'
const DEPARTMENTS = '/organisation/departments/?archived=false&page_size=100'

const label = (position: Position) => `${position.title} (${position.department.name})`

function BossSelect({
  id,
  value,
  positions,
  exclude,
  disabled,
  onChange,
}: {
  id: string
  value: string
  positions: Position[]
  exclude?: string
  disabled?: boolean
  onChange: (value: string) => void
}) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">Nobody (top of the line)</option>
      {positions
        .filter((position) => !position.is_archived && position.id !== exclude)
        .map((position) => (
          <option key={position.id} value={position.id}>
            {label(position)}
          </option>
        ))}
    </select>
  )
}

function CreateForm({
  departments,
  positions,
  onDone,
}: {
  departments: Department[]
  positions: Position[]
  onDone: () => void
}) {
  const [department, setDepartment] = useState('')
  const [title, setTitle] = useState('')
  const [reportsTo, setReportsTo] = useState('')
  const [isHead, setIsHead] = useState(false)
  const action = useAction()

  async function submit(event: FormEvent) {
    event.preventDefault()
    const ok = await action.run(async () => {
      await api('/organisation/positions/', {
        method: 'POST',
        body: {
          department,
          title,
          reports_to: reportsTo || null,
          is_department_head_position: isHead,
        },
      })
      return `Position "${title}" created.`
    })
    if (ok) {
      setTitle('')
      setReportsTo('')
      setIsHead(false)
      onDone()
    }
  }

  return (
    <form className="card" onSubmit={submit} aria-label="New position">
      <h2>New position</h2>
      <div className="field">
        <label htmlFor="new-pos-dept">Department</label>
        <select
          id="new-pos-dept"
          value={department}
          onChange={(event) => setDepartment(event.target.value)}
        >
          <option value="">Choose a department…</option>
          {departments.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="new-pos-title">Title</label>
        <input
          id="new-pos-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="new-pos-boss">Reports to</label>
        <BossSelect
          id="new-pos-boss"
          value={reportsTo}
          positions={positions}
          onChange={setReportsTo}
        />
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={isHead}
          onChange={(event) => setIsHead(event.target.checked)}
        />{' '}
        This is the department head post
      </label>
      {action.error && (
        <p role="alert" className="form-error">
          {action.error}
        </p>
      )}
      {action.message && <p role="status">{action.message}</p>}
      <div>
        <button type="submit" className="button primary" disabled={action.busy}>
          Create position
        </button>
      </div>
    </form>
  )
}

function Editor({
  id,
  positions,
  canEdit,
  canArchive,
  onChanged,
}: {
  id: string
  positions: Position[]
  canEdit: boolean
  canArchive: boolean
  onChanged: () => void
}) {
  const [position, setPosition] = useState<Position | null>(null)
  const [title, setTitle] = useState('')
  const [reportsTo, setReportsTo] = useState('')
  const [isHead, setIsHead] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const action = useAction()

  const load = useCallback(async () => {
    try {
      const detail = await api<Position>(`/organisation/positions/${id}/`)
      setPosition(detail)
      setTitle(detail.title)
      setReportsTo(detail.reports_to?.id ?? '')
      setIsHead(detail.is_department_head_position)
      setLoadError(null)
    } catch (caught) {
      setLoadError(describeError(caught))
    }
  }, [id])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  if (loadError)
    return (
      <p role="alert" className="form-error">
        {loadError}
      </p>
    )
  if (!position) return <p className="muted">Loading…</p>

  const refresh = async () => {
    await load()
    onChanged()
  }
  const blockers = position.archive_blockers ?? []
  const frozen = !canEdit || position.is_archived

  async function save(event: FormEvent) {
    event.preventDefault()
    if (
      await action.run(async () => {
        await api(`/organisation/positions/${id}/`, {
          method: 'PATCH',
          body: { title, reports_to: reportsTo || null, is_department_head_position: isHead },
        })
        return 'Saved.'
      })
    )
      await refresh()
  }

  async function archive() {
    if (!window.confirm(`Archive ${position!.title}?`)) return
    if (
      await action.run(async () => {
        await api(`/organisation/positions/${id}/archive/`, { method: 'POST', body: {} })
        return 'Position archived.'
      })
    )
      await refresh()
  }

  async function restore() {
    if (
      await action.run(async () => {
        await api(`/organisation/positions/${id}/restore/`, { method: 'POST', body: {} })
        return 'Position restored.'
      })
    )
      await refresh()
  }

  return (
    <section className="card" aria-label={`Position ${position.title}`}>
      <h2>
        {position.title} {position.is_archived && <span className="badge warn">Archived</span>}
      </h2>
      <p className="muted small">
        {position.department.name} · held by {position.holder_count ?? 0}{' '}
        {position.holder_count === 1 ? 'person' : 'people'}
      </p>
      {action.error && (
        <p role="alert" className="form-error">
          {action.error}
        </p>
      )}
      {action.message && <p role="status">{action.message}</p>}
      <form onSubmit={save}>
        <div className="field">
          <label htmlFor="pos-title">Title</label>
          <input
            id="pos-title"
            value={title}
            disabled={frozen}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="pos-boss">Reports to</label>
          <BossSelect
            id="pos-boss"
            value={reportsTo}
            positions={positions}
            exclude={position.id}
            disabled={frozen}
            onChange={setReportsTo}
          />
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={isHead}
            disabled={frozen}
            onChange={(event) => setIsHead(event.target.checked)}
          />{' '}
          Department head post
        </label>
        {!frozen && (
          <div>
            <button type="submit" className="button primary" disabled={action.busy}>
              Save changes
            </button>
          </div>
        )}
      </form>
      {position.is_archived
        ? canEdit && (
            <button type="button" className="button" disabled={action.busy} onClick={restore}>
              Restore position
            </button>
          )
        : canArchive && (
            <div>
              <h3>Archive</h3>
              {blockers.length > 0 ? (
                <>
                  <p>It cannot be archived yet:</p>
                  <ul>
                    {blockers.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="muted small">Nobody uses this position, so it can be archived.</p>
              )}
              <button
                type="button"
                className="button danger"
                disabled={action.busy || blockers.length > 0}
                onClick={archive}
              >
                Archive position
              </button>
            </div>
          )}
    </section>
  )
}

export function PositionsPanel() {
  const can = useCan()
  const [positions, setPositions] = useState<Position[] | null>(null)
  const [departments, setDepartments] = useState<Department[]>([])
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [rows, depts] = await Promise.all([
        fetchAll<Position>(POSITIONS),
        fetchAll<Department>(DEPARTMENTS),
      ])
      setPositions(rows)
      setDepartments(depts)
      setError(null)
    } catch (caught) {
      setError(describeError(caught))
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  const shown = (positions ?? []).filter((item) => !filter || item.department.id === filter)

  return (
    <div className="roles-layout">
      <div>
        <div className="field">
          <label htmlFor="pos-filter">Show positions in</label>
          <select
            id="pos-filter"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="">All departments</option>
            {departments.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        {!positions && !error && <p className="muted">Loading…</p>}
        {positions && shown.length === 0 && <p className="card">No positions here yet.</p>}
        <ul className="role-list" aria-label="Positions">
          {shown.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={`role-button${selected === item.id ? ' current' : ''}`}
                aria-pressed={selected === item.id}
                onClick={() => setSelected(item.id)}
              >
                <strong>{item.title}</strong>
                <span className="muted small">
                  {item.department.name}
                  {item.is_archived ? ' · Archived' : ` · ${item.holder_count ?? 0} holding`}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {can('administration', 'CREATE') && positions && (
          <CreateForm departments={departments} positions={positions} onDone={load} />
        )}
      </div>
      <div>
        {selected ? (
          <Editor
            key={selected}
            id={selected}
            positions={positions ?? []}
            canEdit={can('administration', 'EDIT')}
            canArchive={can('administration', 'DELETE')}
            onChanged={load}
          />
        ) : (
          <p className="card muted">Choose a position to see or change it.</p>
        )}
      </div>
    </div>
  )
}
