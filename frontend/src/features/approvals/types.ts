export interface Abilities {
  edit: boolean
  submit: boolean
  cancel: boolean
  review: boolean
  approve: boolean
  reject: boolean
  comment: boolean
}

export interface PersonRef {
  id: string
  name: string
}

export interface RequestSummary {
  id: string
  request_number: string | null
  request_type: string
  type_label: string
  title: string
  status: string
  risk_level: string
  amount_tzs: number | null
  requester: PersonRef | null
  department: { id: string; name: string } | null
  current_step: number
  waiting_for: PersonRef[]
  submitted_at: string | null
  decided_at: string | null
  created_at: string
  can: Abilities
}

export interface RouteStep {
  order: number
  label: string
  source: string
  escalated_to: string | null
  state: 'done' | 'current' | 'waiting' | 'stopped'
}

export interface HistoryEntry {
  id: number
  action: string
  actor: PersonRef | null
  from_status: string
  to_status: string
  step: number
  comment: string
  at: string
}

export interface RequestDetail extends RequestSummary {
  description: string
  decision_comment: string
  payload: Record<string, unknown>
  version: number
  needs_password: boolean
  route: RouteStep[]
  history: HistoryEntry[]
}

export interface NotificationItem {
  id: string
  title: string
  body: string
  request_id: string | null
  created_at: string
  is_read: boolean
}

export interface Policy {
  id: string
  version_number: number
  state: string
  state_label: string
  low_max: number
  medium_max: number
  always_high: string[]
  reason: string
  is_ratified: boolean
  ratified_by: PersonRef | null
  ratified_at: string | null
  request_id: string | null
  created_at: string
}

export interface LimitsView {
  active: Policy | null
  pending: Policy | null
  history: Policy[]
  kinds: { code: string; label: string }[]
  explanation: string
  can_propose: boolean
}

export interface AccessReview {
  generated_at: string
  hosting: { region: string | null; note: string }
  classes: {
    code: string
    label: string
    classification: string
    stored: string
    people: { id: string; name: string; username: string; scope: string; roles: string[] }[]
  }[]
  sensitive_roles: { id: string; name: string; reasons: string[]; holders: string[] }[]
  outside_the_application: string[]
}

export const STATUS_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  SUBMITTED: 'Submitted',
  UNDER_REVIEW: 'Under review',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  CANCELLED: 'Cancelled',
}

export const ACTION_LABELS: Record<string, string> = {
  CREATE: 'Draft created',
  SUBMIT: 'Submitted',
  REVIEW: 'Review started',
  APPROVE: 'Approved',
  REJECT: 'Rejected',
  CANCEL: 'Cancelled',
  COMMENT: 'Comment',
  ESCALATE: 'Escalated',
}

export const RISK_LABELS: Record<string, string> = {
  LOW: 'Low risk',
  MEDIUM: 'Medium risk',
  HIGH: 'High risk',
}

export const CLASSIFICATION_LABELS: Record<string, string> = {
  CHILD_SENSITIVE: 'Child-sensitive',
  FINANCIAL: 'Financial',
  STAFF_PERSONAL: 'Staff personal',
  CONFIDENTIAL: 'Confidential',
  INTERNAL: 'Internal',
}

export function tzs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `TZS ${new Intl.NumberFormat('en-GB').format(value)}`
}
