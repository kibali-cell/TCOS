import { Outlet } from 'react-router-dom'

import { Forbidden } from './Forbidden'
import { useCan } from './usePermissions'

/** Shows the page only to people who hold the permission; others see a plain refusal. */
export function RequirePermission({ module, action }: { module: string; action: string }) {
  const can = useCan()
  return can(module, action) ? <Outlet /> : <Forbidden />
}
