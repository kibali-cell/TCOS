import { useState } from 'react'

import { ChainsPanel } from './ChainsPanel'
import { DepartmentsPanel } from './DepartmentsPanel'
import { OrgChart } from './OrgChart'
import { PositionsPanel } from './PositionsPanel'
import { StaffPanel } from './StaffPanel'

const SECTIONS = [
  { id: 'chart', label: 'Chart' },
  { id: 'departments', label: 'Departments' },
  { id: 'positions', label: 'Positions' },
  { id: 'staff', label: 'Staff' },
  { id: 'chains', label: 'Approval chains' },
] as const

type SectionId = (typeof SECTIONS)[number]['id']

export function OrganisationPage() {
  const [section, setSection] = useState<SectionId>('chart')

  return (
    <>
      <h1>Organisation</h1>
      <p className="muted">
        Departments, the positions in them, who holds each position, and who approves what.
      </p>
      <nav className="org-tabs" aria-label="Organisation sections">
        {SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`button${section === item.id ? ' primary' : ''}`}
            aria-current={section === item.id ? 'page' : undefined}
            onClick={() => setSection(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {section === 'chart' && <OrgChart />}
      {section === 'departments' && <DepartmentsPanel />}
      {section === 'positions' && <PositionsPanel />}
      {section === 'staff' && <StaffPanel />}
      {section === 'chains' && <ChainsPanel />}
    </>
  )
}
