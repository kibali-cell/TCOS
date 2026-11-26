import { useEffect, useState } from 'react'

import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'
import { describeError } from './describeError'
import { CLASSIFICATION_LABELS, type AccessReview } from './types'

export function AccessReviewPage() {
  const [report, setReport] = useState<AccessReview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<AccessReview>('/rbac/access-review/')
      .then(setReport)
      .catch((e) => setError(describeError(e)))
  }, [])

  if (error)
    return (
      <p role="alert" className="form-error">
        {error}
      </p>
    )
  if (!report) return <p className="muted">Loading…</p>

  return (
    <>
      <h1>Access review</h1>
      <p className="muted">
        Where sensitive data is kept and who can see it, read live from the permission settings.
        Generated {formatDateTime(report.generated_at)}. Opening this page is recorded in the audit
        log.
      </p>
      <section className="card" aria-label="Where the server runs">
        <h2>Where the server runs</h2>
        <p>
          <strong>{report.hosting.region ?? 'Not set'}</strong> — {report.hosting.note}
        </p>
      </section>
      {report.classes.map((item) => (
        <section key={item.code} className="card" aria-label={item.label}>
          <h2>
            {item.label} <span className="badge">{CLASSIFICATION_LABELS[item.classification]}</span>
          </h2>
          <p className="muted small">{item.stored}</p>
          {item.people.length === 0 ? (
            <p>Nobody can see this.</p>
          ) : (
            <ul className="plain-list">
              {item.people.map((p) => (
                <li key={p.id}>
                  {p.name} ({p.username}) — {p.scope.toLowerCase()}
                  {p.roles.length > 0 && (
                    <span className="muted small"> via {p.roles.join(', ')}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
      <section className="card" aria-label="Sensitive roles">
        <h2>Sensitive roles and who holds them</h2>
        {report.sensitive_roles.map((role) => (
          <div key={role.id}>
            <strong>{role.name}</strong>: {role.holders.length ? role.holders.join(', ') : 'nobody'}
          </div>
        ))}
      </section>
      <section className="card" aria-label="Outside the application">
        <h2>Who can reach the data outside this application</h2>
        <ul>
          {report.outside_the_application.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>
    </>
  )
}
