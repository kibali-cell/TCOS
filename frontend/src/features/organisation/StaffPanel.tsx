import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { api } from '../../lib/api'
import { useCan } from '../auth/usePermissions'
import { PersonPicker } from './PersonPicker'
import { describeError, fetchAll, useAction } from './shared'
import type { Assignment, Paged, Person, Position } from './types'

const POSITIONS = '/organisation/positions/?archived=false&page_size=100'

function PositionSelect({
  id,
  value,
  positions,
  onChange,
}: {
  id: string
  value: string
  positions: Position[]
  onChange: (value: string) => void
}) {
  return (
    <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">Choose a position…</option>
      {positions.map((position) => (
        <option key={position.id} value={position.id}>
          {position.title} ({position.department.name})
        </option>
      ))}
    </select>
  )
}

function AssignForm({ positions, onDone }: { positions: Position[]; onDone: () => void }) {
  const [person, setPerson] = useState<Person | null>(null)
  const [position, setPosition] = useState('')
  const action = useAction()

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!person) return
    const who = person.full_name
    const ok = await action.run(async () => {
      await api('/organisation/assignments/', {
        method: 'POST',
        body: { user: person.id, position },
      })
      return `${who} assigned.`
    })
    if (ok) {
      setPerson(null)
      setPosition('')
      onDone()
    }
  }

  return (
    <form className="card" onSubmit={submit} aria-label="Assign a person">
      <h2>Assign a person to a position</h2>
      <PersonPicker label="Person" value={person} onChange={setPerson} />
      <div className="field">
        <label htmlFor="assign-position">Position</label>
        <PositionSelect
          id="assign-position"
          value={position}
          positions={positions}
          onChange={setPosition}
        />
      </div>
      <p className="muted small">
        A person&apos;s first assignment becomes their main one, which decides the department whose
        records they can reach.
      </p>
      {action.error && (
        <p role="alert" className="form-error">
          {action.error}
        </p>
      )}
      {action.message && <p role="status">{action.message}</p>}
      <button
        type="submit"
        className="button primary"
        disabled={action.busy || !person || !position}
      >
        Assign
      </button>
    </form>
  )
}

function Actions({
  assignment,
  positions,
  canEdit,
  onDone,
}: {
  assignment: Assignment
  positions: Position[]
  canEdit: boolean
  onDone: () => void
}) {
  const [target, setTarget] = useState('')
  const [boss, setBoss] = useState<Person | null>(null)
  const action = useAction()
  const name = assignment.user.full_name

  const act = async (work: () => Promise<string>) => {
    if (await action.run(work)) onDone()
  }

  return (
    <div className="card" role="group" aria-label={`Actions for ${name}`}>
      <h3>
        {name}: {assignment.position.title}
      </h3>
      {action.error && (
        <p role="alert" className="form-error">
          {action.error}
        </p>
      )}
      {action.message && <p role="status">{action.message}</p>}
      {!canEdit && <p className="muted small">You can look at assignments but not change them.</p>}
      {canEdit && assignment.is_current && (
        <>
          <div className="field">
            <label htmlFor={`transfer-${assignment.id}`}>Move to another position</label>
            <PositionSelect
              id={`transfer-${assignment.id}`}
              value={target}
              positions={positions.filter((item) => item.id !== assignment.position.id)}
              onChange={setTarget}
            />
            <button
              type="button"
              className="button"
              disabled={action.busy || !target}
              onClick={() =>
                act(async () => {
                  await api(`/organisation/assignments/${assignment.id}/transfer/`, {
                    method: 'POST',
                    body: { position: target },
                  })
                  return `${name} moved.`
                })
              }
            >
              Transfer
            </button>
          </div>
          <PersonPicker label="Reports to" value={boss} onChange={setBoss} />
          <div className="button-row">
            <button
              type="button"
              className="button"
              disabled={action.busy || !boss}
              onClick={() =>
                act(async () => {
                  await api(`/organisation/assignments/${assignment.id}/`, {
                    method: 'PATCH',
                    body: { reports_to_user: boss?.id ?? null },
                  })
                  return 'Reporting line saved.'
                })
              }
            >
              Save reporting line
            </button>
            {assignment.reports_to_user && (
              <button
                type="button"
                className="button"
                disabled={action.busy}
                onClick={() =>
                  act(async () => {
                    await api(`/organisation/assignments/${assignment.id}/`, {
                      method: 'PATCH',
                      body: { reports_to_user: null },
                    })
                    return 'Reporting line cleared.'
                  })
                }
              >
                Use the position&apos;s line
              </button>
            )}
          </div>
          <div className="button-row">
            {!assignment.is_primary && (
              <button
                type="button"
                className="button"
                disabled={action.busy}
                onClick={() =>
                  act(async () => {
                    await api(`/organisation/assignments/${assignment.id}/make-primary/`, {
                      method: 'POST',
                      body: {},
                    })
                    return 'Now their main assignment.'
                  })
                }
              >
                Make main assignment
              </button>
            )}
            <button
              type="button"
              className="button danger"
              disabled={action.busy}
              onClick={() => {
                if (!window.confirm(`End ${name}'s assignment as ${assignment.position.title}?`))
                  return
                void act(async () => {
                  await api(`/organisation/assignments/${assignment.id}/end/`, {
                    method: 'POST',
                    body: {},
                  })
                  return 'Assignment ended.'
                })
              }}
            >
              End assignment
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export function StaffPanel() {
  const can = useCan()
  const canEdit = can('administration', 'EDIT')
  const [query, setQuery] = useState('')
  const [applied, setApplied] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Paged<Assignment> | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    fetchAll<Position>(POSITIONS)
      .then(setPositions)
      .catch(() => setPositions([]))
  }, [version])

  useEffect(() => {
    const params = new URLSearchParams()
    if (applied) params.set('q', applied)
    if (page > 1) params.set('page', String(page))
    const text = params.toString()
    let cancelled = false
    api<Paged<Assignment>>(`/organisation/assignments/${text ? `?${text}` : ''}`)
      .then((body) => {
        if (cancelled) return
        setData(body)
        setError(null)
      })
      .catch((caught) => {
        if (cancelled) return
        setData(null)
        setError(describeError(caught))
      })
    return () => {
      cancelled = true
    }
  }, [applied, page, version])

  const reload = useCallback(() => {
    setSelected(null)
    setVersion((value) => value + 1)
  }, [])
  const chosen = data?.results.find((item) => item.id === selected) ?? null

  return (
    <div className="roles-layout">
      <div>
        <form
          className="button-row"
          aria-label="Search staff"
          onSubmit={(event) => {
            event.preventDefault()
            setPage(1)
            setApplied(query.trim())
          }}
        >
          <label className="visually-hidden" htmlFor="staff-search">
            Search staff
          </label>
          <input
            id="staff-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by name"
          />
          <button type="submit" className="button">
            Search
          </button>
        </form>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        {!data && !error && <p className="muted">Loading…</p>}
        {data && data.results.length === 0 && <p className="card">Nobody is assigned yet.</p>}
        {data && data.results.length > 0 && (
          <>
            <ul className="role-list" aria-label="Current assignments">
              {data.results.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`role-button${selected === item.id ? ' current' : ''}`}
                    aria-pressed={selected === item.id}
                    onClick={() => setSelected(item.id)}
                  >
                    <strong>{item.user.full_name}</strong>
                    <span className="muted small">
                      {item.position.title}, {item.department.name}
                      {item.is_primary ? ' · main' : ' · additional'}
                    </span>
                    {item.reports_to_user && (
                      <span className="muted small">
                        reports to {item.reports_to_user.full_name}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
            <div className="button-row">
              <button
                type="button"
                className="button"
                disabled={!data.previous}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                Previous
              </button>
              <span className="muted">Page {page}</span>
              <button
                type="button"
                className="button"
                disabled={!data.next}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </div>
      <div>
        {chosen ? (
          <Actions
            key={chosen.id}
            assignment={chosen}
            positions={positions}
            canEdit={canEdit}
            onDone={reload}
          />
        ) : (
          <p className="card muted">Choose a person to move, end or change who they report to.</p>
        )}
        {can('administration', 'CREATE') && <AssignForm positions={positions} onDone={reload} />}
      </div>
    </div>
  )
}
