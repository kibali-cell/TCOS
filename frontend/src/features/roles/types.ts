export interface Catalogue {
  modules: { code: string; name: string }[]
  actions: string[]
  scopes: string[]
}

export interface RoleSummary {
  id: string
  code: string
  name: string
  description: string
  is_system: boolean
  is_active: boolean
  holders?: number
}

export interface Grant {
  module: string
  action: string
  scope: string
}

export interface RoleDetail extends RoleSummary {
  grants: Grant[]
}

/** Matrix state: "module.ACTION" -> scope. A missing key means no access. */
export type Cells = Record<string, string>

export const cellKey = (module: string, action: string) => `${module}.${action}`

export function toCells(grants: Grant[]): Cells {
  return Object.fromEntries(grants.map((g) => [cellKey(g.module, g.action), g.scope]))
}

export function toGrants(cells: Cells): Grant[] {
  return Object.entries(cells)
    .filter(([, scope]) => scope !== '')
    .map(([key, scope]) => {
      const [module, action] = key.split('.')
      return { module, action, scope }
    })
}

export const ACTION_LABELS: Record<string, string> = {
  VIEW: 'View',
  CREATE: 'Create',
  EDIT: 'Edit',
  DELETE: 'Delete',
  APPROVE: 'Approve',
  REJECT: 'Reject',
  EXPORT: 'Export',
  MANAGE_USERS: 'Manage users',
}

export const SCOPE_LABELS: Record<string, string> = {
  ALL: 'All records',
  DEPARTMENT: 'Own department',
  ASSIGNED: 'Assigned to them',
  OWN: 'Their own',
}
