import { Link, useParams } from 'react-router-dom'

import { SystemStatus } from '../features/status/SystemStatus'
import { MODULES } from './modules'

export function DashboardPage() {
  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">
        Institutional figures, approvals and activity will appear here when the dashboard is built.
        Nothing is shown until it comes from the database.
      </p>
      <SystemStatus />
    </>
  )
}

export function ModulePlaceholderPage() {
  const { slug } = useParams()
  const module = MODULES.find((item) => item.slug === slug)

  if (!module) return <NotFoundPage />

  return (
    <>
      <h1>{module.name}</h1>
      <div className="notice" role="status">
        <strong>Not yet available.</strong> This module has not been built yet.
      </div>
    </>
  )
}

export function NotFoundPage() {
  return (
    <>
      <h1>Page not found</h1>
      <p>
        <Link to="/">Return to the dashboard</Link>
      </p>
    </>
  )
}
