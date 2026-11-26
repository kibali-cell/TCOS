export interface AuditRow {
  id: number
  occurred_at: string
  actor_id: string | null
  actor_username: string
  event_type: string
  object_type: string
  object_id: string
  success: boolean
  ip_address: string | null
  request_id: string
}

export interface AuditDetail extends AuditRow {
  user_agent: string
  changes: Record<string, unknown>
  metadata: Record<string, unknown>
  department_id: string | null
  prev_hash: string
  event_hash: string
}

export interface AuditPage {
  count: number
  next: string | null
  previous: string | null
  results: AuditRow[]
}

export interface Filters {
  q: string
  event_type: string
  success: '' | 'true' | 'false'
  date_from: string
  date_to: string
  object_type: string
}

export const NO_FILTERS: Filters = {
  q: '',
  event_type: '',
  success: '',
  date_from: '',
  date_to: '',
  object_type: '',
}

/** Only the filters that are filled in, in the form the API expects. */
export function activeFilters(filters: Filters): Record<string, string> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value.trim() !== ''))
}

/** "FIRST_NAME_CHANGED" style codes read better as "First name changed". */
export function humanise(code: string): string {
  const text = code.toLowerCase().replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** One change as text: "old → new". Values the viewer cannot read as a pair are shown as JSON. */
export function describeChange(value: unknown): string {
  const show = (item: unknown) =>
    item === null || item === undefined
      ? '—'
      : typeof item === 'string'
        ? item
        : JSON.stringify(item)
  if (value && typeof value === 'object' && !Array.isArray(value) && 'to' in value) {
    const pair = value as { from?: unknown; to?: unknown }
    return `${show(pair.from)} → ${show(pair.to)}`
  }
  return show(value)
}
