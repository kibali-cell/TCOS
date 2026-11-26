import { RISK_LABELS, STATUS_LABELS } from './types'

export function StatusBadge({ status }: { status: string }) {
  const tone = status === 'REJECTED' || status === 'CANCELLED' ? ' warn' : ''
  return <span className={`badge${tone}`}>{STATUS_LABELS[status] ?? status}</span>
}

export function RiskBadge({ risk }: { risk: string }) {
  return (
    <span className={`badge${risk === 'HIGH' ? ' warn' : ''}`}>{RISK_LABELS[risk] ?? risk}</span>
  )
}
