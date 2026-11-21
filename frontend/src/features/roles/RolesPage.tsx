import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'

import { ApiError, api, fieldErrors } from '../../lib/api'
import { useCan } from '../auth/usePermissions'
import { MatrixEditor } from './MatrixEditor'
import {
  toCells,
  toGrants,
  type Catalogue,
  type Cells,
  type RoleDetail,
  type RoleSummary,
} from './types'

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    const details = Object.values(fieldErrors(error)).flat()
    return details.length > 0 ? details.join(' ') : error.message
  }
  return 'Could not reach the server. Please try again.'
}

export function RolesPage() {
  const can = useCan()
  const canManage = can('users', 'MANAGE_USERS')

  const [catalogue, setCatalogue] = useState<Catalogue | null>(null)
  const [roles, setRoles] = useState<RoleSummary[] | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [selected, setSelected] = useState<RoleDetail | null>(null)
  const [cells, setCells] = useState<Cells>({})
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [newName, setNewName] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reloadRoles = useCallback(
    () => api<{ results: RoleSummary[] }>('/rbac/roles/').then((data) => setRoles(data.results)),
    [],
  )

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api<Catalogue>('/rbac/catalogue/'),
      api<{ results: RoleSummary[] }>('/rbac/roles/'),
    ])
      .then(([cat, list]) => {
        if (cancelled) return
        setCatalogue(cat)
        setRoles(list.results)
      })
      .catch(() => {
        if (!cancelled) setLoadError(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const savedCells = useMemo(() => (selected ? toCells(selected.grants) : {}), [selected])
  const dirty = useMemo(() => {
    const keys = new Set([...Object.keys(savedCells), ...Object.keys(cells)])
    return [...keys].some((key) => (savedCells[key] ?? '') !== (cells[key] ?? ''))
  }, [savedCells, cells])

  function show(role: RoleDetail) {
    setSelected(role)
    setCells(toCells(role.grants))
    setName(role.name)
    setDescription(role.description)
  }

  async function choose(id: string) {
    if (dirty && !window.confirm('Discard the permission changes you have not saved?')) return
    setMessage(null)
    setError(null)
    try {
      show(await api<RoleDetail>(`/rbac/roles/${id}/`))
    } catch (caught) {
      setError(describe(caught))
    }
  }

  async function run(action: () => Promise<string>) {
    setBusy(true)
    setMessage(null)
    setError(null)
    try {
      setMessage(await action())
    } catch (caught) {
      setError(describe(caught))
    } finally {
      setBusy(false)
    }
  }

  const savePermissions = () =>
    run(async () => {
      const role = await api<RoleDetail>(`/rbac/roles/${selected!.id}/grants/`, {
        method: 'PUT',
        body: { grants: toGrants(cells) },
      })
      show(role)
      return 'Permissions saved. They apply from the next request anyone makes.'
    })

  const saveDetails = (event: FormEvent) => {
    event.preventDefault()
    return run(async () => {
      const role = await api<RoleDetail>(`/rbac/roles/${selected!.id}/`, {
        method: 'PATCH',
        body: { name, description },
      })
      setSelected((current) => (current ? { ...current, ...role, grants: current.grants } : role))
      await reloadRoles()
      return 'Role details saved.'
    })
  }

  const setActive = (value: boolean) =>
    run(async () => {
      const role = await api<RoleDetail>(`/rbac/roles/${selected!.id}/`, {
        method: 'PATCH',
        body: { is_active: value },
      })
      setSelected((current) => (current ? { ...current, is_active: role.is_active } : role))
      await reloadRoles()
      return value ? 'Role activated.' : 'Role deactivated. Its holders lose its permissions now.'
    })

  const createRole = (event: FormEvent) => {
    event.preventDefault()
    return run(async () => {
      const role = await api<RoleDetail>('/rbac/roles/', {
        method: 'POST',
        body: { name: newName, grants: [] },
      })
      setNewName('')
      await reloadRoles()
      show(role)
      return `Role "${role.name}" created. Choose its permissions below.`
    })
  }

  const deleteRole = () => {
    if (!window.confirm(`Delete the role "${selected!.name}"? This cannot be undone.`)) return
    return run(async () => {
      await api(`/rbac/roles/${selected!.id}/`, { method: 'DELETE' })
      setSelected(null)
      setCells({})
      await reloadRoles()
      return 'Role deleted.'
    })
  }

  if (loadError) {
    return (
      <>
        <h1>Roles and permissions</h1>
        <p role="alert" className="form-error">
          Could not load roles.
        </p>
      </>
    )
  }
  if (!catalogue || !roles) {
    return (
      <>
        <h1>Roles and permissions</h1>
        <p role="status">Loading…</p>
      </>
    )
  }

  return (
    <>
      <h1>Roles and permissions</h1>
      <p className="muted">
        A person may hold several roles; they get everything all their roles allow, using the widest
        scope for each action.
      </p>
      {!canManage && (
        <p className="notice" role="status">
          You can look at roles but not change them.
        </p>
      )}

      <div className="roles-layout">
        <section className="card" aria-labelledby="roles-heading">
          <h2 id="roles-heading">Roles</h2>
          <ul className="role-list" aria-label="Roles">
            {roles.map((role) => (
              <li key={role.id}>
                <button
                  type="button"
                  className={`role-button${selected?.id === role.id ? ' current' : ''}`}
                  aria-pressed={selected?.id === role.id}
                  onClick={() => void choose(role.id)}
                >
                  <span>{role.name}</span>{' '}
                  <span className="muted small">
                    {role.holders ?? 0} {role.holders === 1 ? 'person' : 'people'}
                    {role.is_active ? '' : ' · inactive'}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {canManage && (
            <form onSubmit={createRole} className="new-role">
              <div className="field">
                <label htmlFor="new-role-name">New role name</label>
                <input
                  id="new-role-name"
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                />
              </div>
              <button type="submit" className="button" disabled={busy || !newName.trim()}>
                Create role
              </button>
            </form>
          )}
        </section>

        <section className="card" aria-labelledby="editor-heading">
          {!selected ? (
            <>
              <h2 id="editor-heading">Permissions</h2>
              <p className="muted">Choose a role to see what it allows.</p>
            </>
          ) : (
            <>
              <h2 id="editor-heading">
                {selected.name}
                {selected.is_system && <span className="badge">Built-in</span>}
                {!selected.is_active && <span className="badge warn">Inactive</span>}
              </h2>

              <form onSubmit={saveDetails}>
                <div className="field">
                  <label htmlFor="role-name">Role name</label>
                  <input
                    id="role-name"
                    value={name}
                    disabled={!canManage}
                    onChange={(event) => setName(event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="role-description">Description</label>
                  <input
                    id="role-description"
                    value={description}
                    disabled={!canManage}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </div>
                {canManage && (
                  <div className="button-row">
                    <button
                      type="submit"
                      className="button"
                      disabled={
                        busy ||
                        !name.trim() ||
                        (name === selected.name && description === selected.description)
                      }
                    >
                      Save details
                    </button>
                    {selected.code !== 'ADMINISTRATOR' && (
                      <button
                        type="button"
                        className="button"
                        disabled={busy}
                        onClick={() => void setActive(!selected.is_active)}
                      >
                        {selected.is_active ? 'Deactivate role' : 'Activate role'}
                      </button>
                    )}
                    {!selected.is_system && (
                      <button
                        type="button"
                        className="button danger-text"
                        disabled={busy}
                        onClick={() => void deleteRole()}
                      >
                        Delete role
                      </button>
                    )}
                  </div>
                )}
              </form>

              <h3>What this role allows</h3>
              <p className="muted small">
                Each box sets how far one action reaches. “No access” means the role cannot do it.
              </p>
              <MatrixEditor
                catalogue={catalogue}
                cells={cells}
                disabled={!canManage || busy}
                onChange={(key, scope) => setCells((current) => ({ ...current, [key]: scope }))}
              />

              {canManage && (
                <div className="button-row sticky-actions">
                  <button
                    type="button"
                    className="button primary"
                    disabled={busy || !dirty}
                    onClick={() => void savePermissions()}
                  >
                    Save permissions
                  </button>
                  <button
                    type="button"
                    className="button"
                    disabled={busy || !dirty}
                    onClick={() => setCells(savedCells)}
                  >
                    Discard changes
                  </button>
                  {dirty && <span className="muted small">Unsaved changes</span>}
                </div>
              )}
            </>
          )}

          {message && (
            <p role="status" className="status-ok">
              {message}
            </p>
          )}
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
        </section>
      </div>
    </>
  )
}
