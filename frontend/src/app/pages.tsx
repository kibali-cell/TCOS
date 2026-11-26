import { Link, useParams } from 'react-router-dom'

import { Forbidden } from '../features/auth/Forbidden'
import { useCan } from '../features/auth/usePermissions'
import { MODULES } from './modules'

export function ModulePlaceholderPage() {
  const { slug } = useParams()
  const can = useCan()
  const module = MODULES.find((item) => item.slug === slug)

  if (!module) return <NotFoundPage />
  if (!can(module.permission, 'VIEW')) return <Forbidden />

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
