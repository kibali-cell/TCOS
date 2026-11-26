import { useCallback, useEffect, useState } from 'react'

import { api } from '../../lib/api'
import { useCan } from '../auth/usePermissions'
import { PersonPicker } from './PersonPicker'
import { describeError, fetchAll, useAction } from './shared'
import type { ChainStep, Department, Options, Person, Position } from './types'

interface Draft {
  key: number
  approver_type: string
  position: string
  role: string
  user: Person | null
  userLabel: string
}

let nextKey = 1
const blank = (type = 'DEPARTMENT_HEAD'): Draft => ({
  key: nextKey++,
  approver_type: type,
  position: '',
  role: '',
  user: null,
  userLabel: '',
})

function fromServer(step: ChainStep): Draft {
  return {
    key: nextKey++,
    approver_type: step.approver_type,
    position: step.position ?? '',
    role: step.role ?? '',
    user: step.user ? { id: step.user, full_name: step.label, username: '' } : null,
    userLabel: step.label,
  }
}

function toServer(draft: Draft) {
  const step: Record<string, string> = { approver_type: draft.approver_type }
  if (draft.approver_type === 'POSITION') step.position = draft.position
  if (draft.approver_type === 'ROLE') step.role = draft.role
  if (draft.approver_type === 'USER' && draft.user) step.user = draft.user.id
  return step
}

export function ChainsPanel() {
  const can = useCan()
  const canEdit = can('administration', 'EDIT')
  const [options, setOptions] = useState<Options | null>(null)
  const [departments, setDepartments] = useState<Department[]>([])
  const [positions, setPositions] = useState<Position[]>([])
  const [department, setDepartment] = useState('')
  const [requestType, setRequestType] = useState('DEFAULT')
  const [chains, setChains] = useState<Record<string, ChainStep[]>>({})
  const [steps, setSteps] = useState<Draft[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const action = useAction()

  useEffect(() => {
    Promise.all([
      api<Options>('/organisation/options/'),
      fetchAll<Department>('/organisation/departments/?archived=false&page_size=100'),
      fetchAll<Position>('/organisation/positions/?archived=false&page_size=100'),
    ])
      .then(([opts, depts, rows]) => {
        setOptions(opts)
        setDepartments(depts)
        setPositions(rows)
      })
      .catch((caught) => setLoadError(describeError(caught)))
  }, [])

  const type = requestType.trim().toUpperCase()

  const loadChains = useCallback(async (id: string, wanted: string) => {
    try {
      const body = await api<{ chains: Record<string, ChainStep[]> }>(
        `/organisation/departments/${id}/approval-chains/`,
      )
      setChains(body.chains)
      setSteps((body.chains[wanted] ?? []).map(fromServer))
      setLoadError(null)
    } catch (caught) {
      setLoadError(describeError(caught))
    }
  }, [])

  const choose = (id: string) => {
    setDepartment(id)
    action.clear()
    if (id) void loadChains(id, type)
    else {
      setChains({})
      setSteps([])
    }
  }

  const showType = (wanted: string) => {
    setRequestType(wanted)
    setSteps((chains[wanted.trim().toUpperCase()] ?? []).map(fromServer))
    action.clear()
  }

  const update = (key: number, patch: Partial<Draft>) =>
    setSteps((current) => current.map((step) => (step.key === key ? { ...step, ...patch } : step)))
  const move = (index: number, by: number) =>
    setSteps((current) => {
      const next = [...current]
      const target = index + by
      if (target < 0 || target >= next.length) return current
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })

  async function save() {
    const ok = await action.run(async () => {
      await api(`/organisation/departments/${department}/approval-chains/${type}/`, {
        method: 'PUT',
        body: { steps: steps.map(toServer) },
      })
      return steps.length === 0 ? 'Chain removed.' : 'Chain saved.'
    })
    if (ok) await loadChains(department, type)
  }

  const max = options?.max_chain_steps ?? 6
  const incomplete = steps.some(
    (step) =>
      (step.approver_type === 'POSITION' && !step.position) ||
      (step.approver_type === 'ROLE' && !step.role) ||
      (step.approver_type === 'USER' && !step.user),
  )

  return (
    <section aria-label="Approval chains">
      <p className="muted">
        Who must approve a request from each department, in order. The system works out the actual
        approver when a request is sent; the person asking never chooses. Chains start to be used
        when the Approval Centre is added.
      </p>
      {loadError && (
        <p role="alert" className="form-error">
          {loadError}
        </p>
      )}
      <div className="field">
        <label htmlFor="chain-dept">Department</label>
        <select id="chain-dept" value={department} onChange={(event) => choose(event.target.value)}>
          <option value="">Choose a department…</option>
          {departments.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>

      {department && (
        <>
          <div className="field">
            <label htmlFor="chain-type">Kind of request</label>
            <input
              id="chain-type"
              value={requestType}
              onChange={(event) => showType(event.target.value)}
            />
            <p className="muted small">
              DEFAULT applies to any request that has no chain of its own.
            </p>
            {Object.keys(chains).length > 0 && (
              <div className="button-row" aria-label="Existing chains">
                {Object.keys(chains).map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="button"
                    onClick={() => showType(name)}
                  >
                    {name} ({chains[name].length})
                  </button>
                ))}
              </div>
            )}
          </div>

          <ol className="chain-steps" aria-label={`Chain for ${type}`}>
            {steps.map((step, index) => (
              <li key={step.key} className="card">
                <div className="field">
                  <label htmlFor={`step-type-${step.key}`}>Step {index + 1} approver</label>
                  <select
                    id={`step-type-${step.key}`}
                    value={step.approver_type}
                    disabled={!canEdit}
                    onChange={(event) =>
                      update(step.key, {
                        approver_type: event.target.value,
                        position: '',
                        role: '',
                        user: null,
                      })
                    }
                  >
                    {(options?.approver_types ?? []).map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </div>
                {step.approver_type === 'POSITION' && (
                  <div className="field">
                    <label htmlFor={`step-pos-${step.key}`}>Position</label>
                    <select
                      id={`step-pos-${step.key}`}
                      value={step.position}
                      disabled={!canEdit}
                      onChange={(event) => update(step.key, { position: event.target.value })}
                    >
                      <option value="">Choose a position…</option>
                      {positions.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.title} ({item.department.name})
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {step.approver_type === 'ROLE' && (
                  <div className="field">
                    <label htmlFor={`step-role-${step.key}`}>Role</label>
                    <select
                      id={`step-role-${step.key}`}
                      value={step.role}
                      disabled={!canEdit}
                      onChange={(event) => update(step.key, { role: event.target.value })}
                    >
                      <option value="">Choose a role…</option>
                      {(options?.roles ?? []).map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {step.approver_type === 'USER' && canEdit && (
                  <PersonPicker
                    label="Approver"
                    value={step.user}
                    onChange={(person) => update(step.key, { user: person })}
                  />
                )}
                {step.approver_type === 'USER' && !canEdit && (
                  <p>{step.userLabel || step.user?.full_name}</p>
                )}
                {canEdit && (
                  <div className="button-row">
                    <button
                      type="button"
                      className="button"
                      disabled={index === 0}
                      onClick={() => move(index, -1)}
                      aria-label={`Move step ${index + 1} up`}
                    >
                      Up
                    </button>
                    <button
                      type="button"
                      className="button"
                      disabled={index === steps.length - 1}
                      onClick={() => move(index, 1)}
                      aria-label={`Move step ${index + 1} down`}
                    >
                      Down
                    </button>
                    <button
                      type="button"
                      className="button danger"
                      onClick={() =>
                        setSteps((current) => current.filter((x) => x.key !== step.key))
                      }
                      aria-label={`Remove step ${index + 1}`}
                    >
                      Remove
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ol>
          {steps.length === 0 && (
            <p className="card">No approval chain for {type || 'this type'}.</p>
          )}

          {action.error && (
            <p role="alert" className="form-error">
              {action.error}
            </p>
          )}
          {action.message && <p role="status">{action.message}</p>}
          {canEdit && (
            <div className="button-row">
              <button
                type="button"
                className="button"
                disabled={steps.length >= max}
                onClick={() => setSteps((current) => [...current, blank()])}
              >
                Add a step
              </button>
              <button
                type="button"
                className="button primary"
                disabled={action.busy || incomplete || !type}
                onClick={save}
              >
                Save chain
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
