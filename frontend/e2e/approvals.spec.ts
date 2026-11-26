import { expect, test, type Page } from '@playwright/test'

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})
const LONG = 'A request title that is long enough that it has to wrap on a narrow phone screen'
const NAME = 'Someone With A Considerably Long Full Name'

const summary = {
  id: 'r1',
  request_number: 'TCOS-REQ-2026-000001',
  request_type: 'GENERAL',
  type_label: 'General request',
  title: LONG,
  status: 'SUBMITTED',
  risk_level: 'HIGH',
  amount_tzs: 2500000,
  requester: { id: 'u1', name: NAME },
  department: { id: 'd1', name: 'Finance and Administration Department' },
  current_step: 1,
  waiting_for: [{ id: 'u2', name: NAME }],
  submitted_at: '2026-11-20T04:00:00Z',
  decided_at: null,
  created_at: '2026-11-20T03:00:00Z',
  can: {
    edit: false,
    submit: false,
    cancel: false,
    review: true,
    approve: true,
    reject: true,
    comment: true,
  },
}
const detail = {
  ...summary,
  description: LONG,
  attachments: [],
  can_attach_files: false,
  decision_comment: '',
  payload: { kind: '', kind_label: '' },
  version: 2,
  needs_password: true,
  route: [
    { order: 1, label: NAME, source: 'CHAIN', escalated_to: null, state: 'current' },
    {
      order: 2,
      label: 'Executive Director',
      source: 'CHAIN',
      escalated_to: null,
      state: 'waiting',
    },
  ],
  history: [
    {
      id: 1,
      action: 'SUBMIT',
      actor: { id: 'u1', name: NAME },
      from_status: 'DRAFT',
      to_status: 'SUBMITTED',
      step: 1,
      comment: LONG,
      at: '2026-11-20T04:00:00Z',
    },
  ],
}
const policy = {
  id: 'p1',
  version_number: 1,
  state: 'ACTIVE',
  state_label: 'In force',
  low_max: 200000,
  medium_max: 2000000,
  always_high: ['PAYROLL', 'WRITE_OFF'],
  reason: '',
  is_ratified: false,
  ratified_by: null,
  ratified_at: null,
  request_id: null,
  created_at: '2026-11-01T00:00:00Z',
}
const limits = {
  active: policy,
  pending: null,
  history: [policy],
  kinds: [
    { code: 'PAYROLL', label: 'Payroll' },
    { code: 'WRITE_OFF', label: 'Write-offs' },
  ],
  explanation: 'These limits decide the risk level of a request.',
  can_propose: true,
}
const review = {
  generated_at: '2026-11-22T10:00:00Z',
  hosting: { region: null, note: 'The hosting region has not been decided yet.' },
  classes: [
    {
      code: 'children',
      label: 'Child profiles',
      classification: 'CHILD_SENSITIVE',
      stored: 'Central PostgreSQL database only.',
      people: [
        {
          id: 'u1',
          name: NAME,
          username: 'someone',
          scope: 'ALL',
          roles: ['Social Welfare Officer'],
        },
      ],
    },
  ],
  sensitive_roles: [
    { id: 'r1', name: 'Administrator', reasons: ['Can manage users (users)'], holders: [NAME] },
  ],
  outside_the_application: ['Whoever administers the database server can read the stored data.'],
}

async function signedIn(page: Page) {
  const permissions = {
    approvals: { VIEW: 'ALL', CREATE: 'OWN', APPROVE: 'ASSIGNED', REJECT: 'ASSIGNED' },
    audit: { VIEW: 'ALL' },
    administration: { VIEW: 'ALL', EDIT: 'ALL' },
  }
  await page.route('**/api/v1/auth/me/', (route) =>
    route.fulfill(
      json({
        user: {
          id: 'u9',
          username: 'alice',
          full_name: 'Alice Mwangi',
          email: 'a@example.org',
          phone: '',
          status: 'ACTIVE',
          must_change_password: false,
          last_login: null,
        },
        session: { idle_expires_at: null, absolute_expires_at: null },
        permissions,
        roles: [],
      }),
    ),
  )
  await page.route('**/api/v1/health/', (route) =>
    route.fulfill(json({ status: 'ok', database: 'ok' })),
  )
  await page.route('**/api/v1/approvals/summary/', (route) =>
    route.fulfill(json({ pending: 1, unread_notifications: 0 })),
  )
  await page.route('**/api/v1/approvals/notifications/', (route) =>
    route.fulfill(json({ count: 0, next: null, previous: null, results: [] })),
  )
  await page.route('**/api/v1/approvals/requests/?**', (route) =>
    route.fulfill(json({ count: 1, next: null, previous: null, results: [summary] })),
  )
  await page.route('**/api/v1/approvals/requests/r1/', (route) => route.fulfill(json(detail)))
  await page.route('**/api/v1/approvals/tzs-limits/', (route) => route.fulfill(json(limits)))
  await page.route('**/api/v1/rbac/access-review/', (route) => route.fulfill(json(review)))
}

async function noSideways(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

test('approvals: list, detail, limits and access review fit the screen', async ({ page }) => {
  await signedIn(page)
  await page.goto('/approvals')
  await expect(page.getByText('TCOS-REQ-2026-000001').first()).toBeVisible()
  await noSideways(page)

  await page.goto('/approvals/r1')
  await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()
  await expect(page.getByLabel(/Your password/)).toBeVisible()
  await noSideways(page)

  await page.goto('/approvals/limits')
  await expect(page.getByText(/200,000/).first()).toBeVisible()
  await noSideways(page)

  await page.goto('/administration/access-review')
  await expect(page.getByText('Child profiles').first()).toBeVisible()
  await expect(page.getByText(/hosting region has not been decided/)).toBeVisible()
  await noSideways(page)
})
