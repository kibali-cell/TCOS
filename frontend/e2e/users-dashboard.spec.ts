import { expect, test, type Page } from '@playwright/test'

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})
const NAME = 'Someone With A Considerably Long Full Name'

const user = {
  id: 'u1',
  username: 'someone.with.a.long.username',
  full_name: NAME,
  email: 'someone.with.a.very.long.address@example-organisation.org',
  phone: '+255712345678',
  status: 'ACTIVE',
  department: { id: 'd1', name: 'Finance and Administration Department' },
  position: 'Senior Accounts and Payroll Officer',
  roles: [{ id: 'a1', role_id: 'r1', name: 'Finance Officer', department: null }],
  created_at: '2026-11-01T08:00:00Z',
  last_login: '2026-11-20T08:00:00Z',
  must_change_password: false,
}
const dashboard = {
  figures: [
    {
      key: 'total_children',
      label: 'Total children',
      value: 85,
      source: 'reference',
      source_label: 'Reference figure (not yet verified)',
      reference_value: 85,
      is_verified: false,
      note: 'No records have been entered yet.',
    },
    {
      key: 'total_employees',
      label: 'Employees',
      value: 3,
      source: 'live',
      source_label: 'Live count from records',
      reference_value: 15,
      is_verified: true,
      note: 'Counted from current staff assignments.',
    },
  ],
  approvals: { waiting_for_me: 2, open_in_my_scope: 5, mine_open: 1 },
  finance: { figures: [], note: 'No financial records have been entered yet.' },
  recent_activity: [
    {
      id: 1,
      occurred_at: '2026-11-20T08:00:00Z',
      actor: 'someone',
      event_type: 'USER_CREATED',
      object_type: 'accounts.User',
      success: true,
    },
  ],
  notifications: {
    unread: 1,
    latest: [
      {
        id: 'n1',
        title: 'A request awaits you',
        body: 'TCOS-REQ-2026-000001',
        request_id: null,
        is_read: false,
      },
    ],
  },
  department: { id: 'd1', name: 'Finance and Administration Department' },
}
const departmentDashboard = {
  department: { id: 'd1', name: 'Finance and Administration Department', head: NAME },
  staff_count: 4,
  pending_approvals: {
    count: 1,
    latest: [
      {
        id: 'r1',
        request_number: 'TCOS-REQ-2026-000001',
        title: 'A long request title that wraps on a phone',
        status: 'SUBMITTED',
        requester: NAME,
      },
    ],
  },
  recent_activity: [],
}

async function signedIn(page: Page) {
  const permissions = {
    users: { VIEW: 'ALL', MANAGE_USERS: 'ALL' },
    approvals: { VIEW: 'ALL' },
    audit: { VIEW: 'ALL' },
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
    route.fulfill(json({ pending: 0, unread_notifications: 0 })),
  )
  await page.route('**/api/v1/dashboard/', (route) => route.fulfill(json(dashboard)))
  await page.route('**/api/v1/dashboard/departments/d1/', (route) =>
    route.fulfill(json(departmentDashboard)),
  )
  await page.route('**/api/v1/users/?**', (route) =>
    route.fulfill(json({ count: 1, next: null, previous: null, results: [user] })),
  )
  await page.route('**/api/v1/users/u1/', (route) => route.fulfill(json(user)))
  await page.route('**/api/v1/rbac/roles/', (route) => route.fulfill(json({ results: [] })))
}

async function noSideways(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

test('dashboard, users and department dashboard fit the screen', async ({ page }) => {
  await signedIn(page)
  await page.goto('/')
  await expect(page.getByText('Reference figure (not yet verified)')).toBeVisible()
  await expect(page.getByText('Live count from records')).toBeVisible()
  await noSideways(page)

  await page.goto('/administration/users')
  await expect(page.getByRole('table', { name: 'Users' })).toBeVisible()
  await noSideways(page)

  await page.goto('/administration/users/u1')
  await expect(page.getByRole('heading', { name: NAME })).toBeVisible()
  await noSideways(page)

  await page.goto('/departments/d1/dashboard')
  await expect(page.getByText('Open requests').first()).toBeVisible()
  await noSideways(page)
})

test('printing shows the content without the menu or controls, and the user list as a table', async ({
  page,
}) => {
  await signedIn(page)
  await page.goto('/administration/users')
  await expect(page.getByRole('table', { name: 'Users' })).toBeVisible()
  await page.emulateMedia({ media: 'print' })
  await expect(page.locator('.sidebar')).toBeHidden()
  await expect(page.getByRole('button', { name: 'Print this list' })).toBeHidden()
  await expect(page.getByLabel('Search')).toBeHidden()
  const display = await page
    .getByRole('table', { name: 'Users' })
    .evaluate((el) => getComputedStyle(el).display)
  expect(display).toBe('table')
  await expect(page.getByRole('columnheader', { name: 'Last sign-in' })).toBeVisible()
})
