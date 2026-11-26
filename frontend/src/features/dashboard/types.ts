export interface Figure {
  key: string
  label: string
  value: number | null
  source: 'live' | 'reference' | 'none'
  source_label: string
  reference_value: number | null
  is_verified: boolean
  note: string
}

export interface ActivityRow {
  id: number
  occurred_at: string
  actor: string
  event_type: string
  object_type: string
  success: boolean
}

export interface DashboardData {
  figures: Figure[]
  approvals: { waiting_for_me: number; open_in_my_scope: number; mine_open: number } | null
  finance: { figures: unknown[]; note: string } | null
  recent_activity: ActivityRow[] | null
  notifications: {
    unread: number
    latest: {
      id: string
      title: string
      body: string
      request_id: string | null
      is_read: boolean
    }[]
  }
  department: { id: string; name: string } | null
}

export interface DepartmentDashboardData {
  department: { id: string; name: string; head: string | null }
  staff_count: number
  pending_approvals: {
    count: number
    latest: {
      id: string
      request_number: string | null
      title: string
      status: string
      requester: string
    }[]
  } | null
  recent_activity: ActivityRow[] | null
}
