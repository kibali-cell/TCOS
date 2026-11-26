export interface UserRow {
  id: string
  username: string
  full_name: string
  email: string
  phone: string
  status: string
  department: { id: string; name: string } | null
  position: string | null
  roles: { id: string; role_id: string; name: string; department: string | null }[]
  created_at: string
  last_login: string | null
  must_change_password: boolean
  two_factor_required?: boolean
  two_factor?: { enabled: boolean; required: boolean; setup_required: boolean }
}

export const STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'Active',
  INACTIVE: 'Inactive',
  LOCKED: 'Locked',
  PENDING: 'Pending activation',
}
