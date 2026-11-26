import { useEffect, useState } from 'react'

import { api } from '../../lib/api'
import { describeError } from './shared'
import type { TreeDepartment } from './types'

function Department({ node, depth }: { node: TreeDepartment; depth: number }) {
  const reportsTo = new Map(node.positions.map((position) => [position.id, position.title]))
  return (
    <li>
      <details open={depth === 0}>
        <summary>
          <strong>{node.name}</strong>
          {node.is_archived && <span className="badge warn">Archived</span>}
          <span className="muted small">
            {' '}
            · {node.head ? `Head: ${node.head.full_name}` : 'No head named'} · {node.staff_count}{' '}
            {node.staff_count === 1 ? 'person' : 'people'}
          </span>
        </summary>
        {node.positions.length === 0 ? (
          <p className="muted small">No positions yet.</p>
        ) : (
          <ul className="org-positions">
            {node.positions.map((position) => (
              <li key={position.id}>
                <span>
                  {position.title}
                  {position.is_department_head_position && <span className="badge">Head post</span>}
                  {position.reports_to_id && reportsTo.has(position.reports_to_id) && (
                    <span className="muted small">
                      {' '}
                      reports to {reportsTo.get(position.reports_to_id)}
                    </span>
                  )}
                </span>
                <span className="small">
                  {position.holders.length === 0
                    ? 'Vacant'
                    : position.holders.map((holder) => holder.full_name).join(', ')}
                </span>
              </li>
            ))}
          </ul>
        )}
        {node.children.length > 0 && (
          <ul className="org-tree">
            {node.children.map((child) => (
              <Department key={child.id} node={child} depth={depth + 1} />
            ))}
          </ul>
        )}
      </details>
    </li>
  )
}

export function OrgChart() {
  const [roots, setRoots] = useState<TreeDepartment[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [archived, setArchived] = useState(false)

  useEffect(() => {
    let cancelled = false
    api<{ results: TreeDepartment[] }>(
      `/organisation/tree/${archived ? '?include_archived=true' : ''}`,
    )
      .then((body) => {
        if (cancelled) return
        setRoots(body.results)
        setError(null)
      })
      .catch((caught) => !cancelled && setError(describeError(caught)))
    return () => {
      cancelled = true
    }
  }, [archived])

  return (
    <section aria-label="Organisation chart">
      <label className="check">
        <input
          type="checkbox"
          checked={archived}
          onChange={(event) => setArchived(event.target.checked)}
        />{' '}
        Show archived departments
      </label>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {!roots && !error && <p className="muted">Loading…</p>}
      {roots && roots.length === 0 && <p className="card">No departments yet.</p>}
      {roots && roots.length > 0 && (
        <ul className="org-tree org-root">
          {roots.map((node) => (
            <Department key={node.id} node={node} depth={0} />
          ))}
        </ul>
      )}
    </section>
  )
}
