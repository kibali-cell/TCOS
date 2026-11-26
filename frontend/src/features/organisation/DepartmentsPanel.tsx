import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { api } from '../../lib/api'
import { useCan } from '../auth/usePermissions'
import { describeError, fetchAll, useAction } from './shared'
import type { Department, Paged, Person } from './types'

const LIST = '/organisation/departments/?archived=all&page_size=100'

function CreateForm({ departments, onDone }: { departments: Department[]; onDone: () => void }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [parent, setParent] = useState('')
  const action = useAction()

  async function submit(event: FormEvent) {
    event.preventDefault()
    const ok = await action.run(async () => {
      await api('/organisation/departments/', {
        method: 'POST',
        body: { code, name, description, parent: parent || null },
      })
      return `Department "${name}" created.`
    })
    if (ok) {
      setCode('')
      setName('')
      setDescription('')
      setParent('')
      onDone()
    }
  }

  return (
    <form className="card" onSubmit={submit} aria-label="New department">
      <h2>New department</h2>
      <div className="field">
        <label htmlFor="new-dept-code">Code</label>
        <input
          id="new-dept-code"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="e.g. LAUNDRY"
        />
      </div>
      <div className="field">
        <label htmlFor="new-dept-name">Name</label>
        <input id="new-dept-name" value={name} onChange={(event) => setName(event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="new-dept-description">Description</label>
        <textarea
          id="new-dept-description"
          rows={2}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="new-dept-parent">Sits under</label>
        <select
          id="new-dept-parent"
          value={parent}
          onChange={(event) => setParent(event.target.value)}
        >
          <option value="">Top level</option>
          {departments
            .filter((department) => !department.is_archived)
            .map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
        </select>
      </div>
      {action.error && (
        <p role="alert" className="form-error">
          {action.error}
        </p>
      )}
      {action.message && <p role="status">{action.message}</p>}
      <button type="submit" className="button primary" disabled={action.busy}>
        Create department
      </button>
    </form>
  )
}

function Editor({
  id,
  departments,
  canEdit,
  canArchive,
  onChanged,
}: {
  id: string
  departments: Department[]
  canEdit: boolean
  canArchive: boolean
  onChanged: () => void
}) {
  const [department, setDepartment] = useState<Department | null>(null)
  const [staff, setStaff] = useState<Person[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [parent, setParent] = useState('')
  const [head, setHead] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const action = useAction()

  const load = useCallback(async () => {
    try {
      const detail = await api<Department>(`/organisation/departments/${id}/`)
      const people = await api<Paged<{ user: Person }>>(
        `/organisation/assignments/?department=${id}&page_size=100`,
      )
      const seen = new Map<string, Person>()
      people.results.forEach((row) => seen.set(row.user.id, row.user))
      setStaff([...seen.values()])
      setDepartment(detail)
      setName(detail.name)
      setDescription(detail.description)
      setParent(detail.parent?.id ?? '')
      setHead(detail.head?.id ?? '')
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
  if (!department) return <p className="muted">Loading…</p>

  const refresh = async () => {
    await load()
    onChanged()
  }
  const blockers = department.archive_blockers ?? []

  async function save(event: FormEvent) {
    event.preventDefault()
    if (
      await action.run(async () => {
        await api(`/organisation/departments/${id}/`, {
          method: 'PATCH',
          body: { name, description, parent: parent || null },
        })
        return 'Saved.'
      })
    )
      await refresh()
  }

  async function saveHead() {
    if (
      await action.run(async () => {
        await api(`/organisation/departments/${id}/head/`, {
          method: 'PUT',
          body: { user: head || null },
        })
        return head ? 'Head named.' : 'Head cleared.'
      })
    )
      await refresh()
  }

  async function archive() {
    if (!window.confirm(`Archive ${department!.name}? Its positions are archived with it.`)) return
    if (
      await action.run(async () => {
        await api(`/organisation/departments/${id}/archive/`, { method: 'POST', body: {} })
        return 'Department archived.'
      })
    )
      await refresh()
  }

  async function restore() {
    if (
      await action.run(async () => {
        await api(`/organisation/departments/${id}/restore/`, { method: 'POST', body: {} })
        return 'Department restored. Its positions stay archived until you restore them.'
      })
    )
      await refresh()
  }

  return (
    <section className="card" aria-label={`Department ${department.name}`}>
      <h2>
        {department.name} {department.is_archived && <span className="badge warn">Archived</span>}
      </h2>
      <p className="muted small">
        Code {department.code} · {department.staff_count ?? 0} people ·{' '}
        {department.position_count ?? 0} positions
      </p>
      {action.error && (
        <p role="alert" className="form-error">
          {action.error}
        </p>
      )}
      {action.message && <p role="status">{action.message}</p>}

      <form onSubmit={save}>
        <div className="field">
          <label htmlFor="dept-name">Name</label>
          <input
            id="dept-name"
            value={name}
            disabled={!canEdit || department.is_archived}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="dept-description">Description</label>
          <textarea
            id="dept-description"
            rows={2}
            value={description}
            disabled={!canEdit || department.is_archived}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="dept-parent">Sits under</label>
          <select
            id="dept-parent"
            value={parent}
            disabled={!canEdit || department.is_archived}
            onChange={(event) => setParent(event.target.value)}
          >
            <option value="">Top level</option>
            {departments
              .filter((item) => !item.is_archived && item.id !== department.id)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
          </select>
        </div>
        {canEdit && !department.is_archived && (
          <button type="submit" className="button primary" disabled={action.busy}>
            Save changes
          </button>
        )}
      </form>

      {canEdit && !department.is_archived && (
        <div className="field">
          <label htmlFor="dept-head">Department head</label>
          <select id="dept-head" value={head} onChange={(event) => setHead(event.target.value)}>
            <option value="">No head named</option>
            {staff.map((person) => (
              <option key={person.id} value={person.id}>
                {person.full_name}
              </option>
            ))}
          </select>
          <p className="muted small">Only people who hold a position here can be the head.</p>
          <button type="button" className="button" disabled={action.busy} onClick={saveHead}>
            Save head
          </button>
        </div>
      )}

      {department.is_archived
        ? canEdit && (
            <button type="button" className="button" disabled={action.busy} onClick={restore}>
              Restore department
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
                <p className="muted small">
                  Nothing is using this department, so it can be archived.
                </p>
              )}
              <button
                type="button"
                className="button danger"
                disabled={action.busy || blockers.length > 0}
                onClick={archive}
              >
                Archive department
              </button>
            </div>
          )}
    </section>
  )
}

export function DepartmentsPanel() {
  const can = useCan()
  const canCreate = can('administration', 'CREATE')
  const canEdit = can('administration', 'EDIT')
  const canArchive = can('administration', 'DELETE')
  const [departments, setDepartments] = useState<Department[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setDepartments(await fetchAll<Department>(LIST))
      setError(null)
    } catch (caught) {
      setError(describeError(caught))
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  return (
    <div className="roles-layout">
      <div>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        {!departments && !error && <p className="muted">Loading…</p>}
        {departments && (
          <ul className="role-list" aria-label="Departments">
            {departments.map((department) => (
              <li key={department.id}>
                <button
                  type="button"
                  className={`role-button${selected === department.id ? ' current' : ''}`}
                  aria-pressed={selected === department.id}
                  onClick={() => setSelected(department.id)}
                >
                  <strong>{department.name}</strong>
                  <span className="muted small">
                    {department.is_archived ? 'Archived' : `${department.staff_count ?? 0} people`}
                    {department.parent ? ` · under ${department.parent.name}` : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {canCreate && departments && <CreateForm departments={departments} onDone={load} />}
      </div>
      <div>
        {selected ? (
          <Editor
            key={selected}
            id={selected}
            departments={departments ?? []}
            canEdit={canEdit}
            canArchive={canArchive}
            onChanged={load}
          />
        ) : (
          <p className="card muted">Choose a department to see or change it.</p>
        )}
      </div>
    </div>
  )
}
