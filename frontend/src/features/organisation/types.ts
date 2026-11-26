export interface Person {
  id: string
  full_name: string
  username: string
}

export interface Department {
  id: string
  code: string
  name: string
  description: string
  parent: { id: string; name: string } | null
  head: { id: string; full_name: string } | null
  is_active: boolean
  is_archived: boolean
  version: number
  staff_count: number | null
  position_count: number | null
  archive_blockers?: string[]
}

export interface Position {
  id: string
  title: string
  department: { id: string; name: string }
  reports_to: { id: string; title: string; department: string } | null
  is_department_head_position: boolean
  is_active: boolean
  is_archived: boolean
  version: number
  holder_count: number | null
  archive_blockers?: string[]
}

export interface Assignment {
  id: string
  user: Person
  position: { id: string; title: string }
  department: { id: string; name: string }
  is_primary: boolean
  reports_to_user: Person | null
  start_date: string
  end_date: string | null
  is_current: boolean
}

export interface Paged<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface TreePosition {
  id: string
  title: string
  reports_to_id: string | null
  is_department_head_position: boolean
  holders: { assignment_id: string; user_id: string; full_name: string; is_primary: boolean }[]
}

export interface TreeDepartment {
  id: string
  code: string
  name: string
  description: string
  head: { id: string; full_name: string } | null
  is_archived: boolean
  staff_count: number
  positions: TreePosition[]
  children: TreeDepartment[]
}

export interface ChainStep {
  step_order: number
  approver_type: string
  label: string
  position: string | null
  role: string | null
  user: string | null
}

export interface Options {
  roles: { id: string; name: string }[]
  approver_types: { value: string; label: string }[]
  default_request_type: string
  max_chain_steps: number
}
