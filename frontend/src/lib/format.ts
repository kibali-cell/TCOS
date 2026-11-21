const TIME_ZONE = 'Africa/Dar_es_Salaam'

/** Date and time in the institution's time zone, e.g. "20 Nov 2026, 07:12". */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: TIME_ZONE,
  }).format(date)
}
