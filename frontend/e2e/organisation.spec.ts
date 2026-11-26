import { expect, test, type Page } from '@playwright/test'

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})
const page_ = (results: unknown[]) => ({
  count: results.length,
  next: null,
  previous: null,
  results,
})

const LONG = 'A department with a rather long name that has to wrap on a narrow phone screen'
const department = (id: string, name: string, parent: string | null = null) => ({
  id,
  code: id.toUpperCase(),
  name,
  description: '',
  parent: parent ? { id: parent, name: LONG } : null,
  head: null,
  is_active: true,
  is_archived: false,
  version: 1,
  staff_count: 2,
  position_count: 1,
})
const position = {
  id: 'p1',
  title: 'Head of a department with a very long title indeed',
  department: { id: 'd1', name: LONG },
  reports_to: null,
  is_department_head_position: true,
  is_active: true,
  is_archived: false,
  version: 1,
  holder_count: 1,
}
const assignment = {
  id: 'a1',
  user: { id: 'u1', full_name: 'Someone With A Considerably Long Full Name', username: 'someone' },
  position: { id: 'p1', title: position.title },
  department: { id: 'd1', name: LONG },
  is_primary: true,
  reports_to_user: null,
  start_date: '2026-11-01',
  end_date: null,
  is_current: true,
}
const tree = {
  results: [
    {
      id: 'd1',
      code: 'D1',
      name: LONG,
      description: '',
      head: { id: 'u1', full_name: assignment.user.full_name },
      is_archived: false,
      staff_count: 2,
      positions: [
        {
          id: 'p1',
          title: position.title,
          reports_to_id: null,
          is_department_head_position: true,
          holders: [
            {
              assignment_id: 'a1',
              user_id: 'u1',
              full_name: assignment.user.full_name,
              is_primary: true,
            },
          ],
        },
      ],
      children: [
        {
          id: 'd2',
          code: 'D2',
          name: 'Child',
          description: '',
          head: null,
          is_archived: false,
          staff_count: 0,
          positions: [],
          children: [],
        },
      ],
    },
  ],
}

async function signedIn(page: Page, permissions: object) {
  await page.route('**/api/v1/auth/me/', (route) =>
    route.fulfill(
      json({
        user: {
          id: 'u9',
          username: 'alice',
          full_name: 'Alice Mwangi',
          email: 'alice@example.org',
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
  await page.route('**/api/v1/organisation/tree/', (route) => route.fulfill(json(tree)))
  await page.route('**/api/v1/organisation/departments/?**', (route) =>
    route.fulfill(json(page_([department('d1', LONG), department('d2', 'Child', 'd1')]))),
  )
  await page.route('**/api/v1/organisation/departments/d1/', (route) =>
    route.fulfill(
      json({ ...department('d1', LONG), archive_blockers: ['2 people still work in it'] }),
    ),
  )
  await page.route('**/api/v1/organisation/assignments/?department=**', (route) =>
    route.fulfill(json(page_([assignment]))),
  )
  await page.route('**/api/v1/organisation/positions/?**', (route) =>
    route.fulfill(json(page_([position]))),
  )
  await page.route('**/api/v1/organisation/assignments/', (route) =>
    route.fulfill(json(page_([assignment]))),
  )
  await page.route('**/api/v1/organisation/options/', (route) =>
    route.fulfill(
      json({
        roles: [{ id: 'r1', name: 'Finance Officer' }],
        approver_types: [{ value: 'DEPARTMENT_HEAD', label: 'The department head' }],
        default_request_type: 'DEFAULT',
        max_chain_steps: 6,
      }),
    ),
  )
  await page.route('**/api/v1/organisation/departments/d1/approval-chains/', (route) =>
    route.fulfill(json({ chains: {} })),
  )
}

async function noSideways(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

const FULL = { administration: { VIEW: 'ALL', CREATE: 'ALL', EDIT: 'ALL', DELETE: 'ALL' } }

test('organisation: every section fits the screen with long names', async ({ page }) => {
  await signedIn(page, FULL)
  await page.goto('/administration/organisation')
  await expect(page.getByRole('heading', { name: 'Organisation' })).toBeVisible()
  await expect(page.getByText('Child')).toBeVisible()
  await noSideways(page)

  await page.getByRole('button', { name: 'Departments' }).click()
  await page
    .getByRole('button', { name: new RegExp(LONG.slice(0, 20)) })
    .first()
    .click()
  await expect(page.getByText('2 people still work in it')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Archive department' })).toBeDisabled()
  await noSideways(page)

  await page.getByRole('button', { name: 'Positions' }).click()
  await expect(page.getByRole('button', { name: /Head of a department/ })).toBeVisible()
  await noSideways(page)

  await page.getByRole('button', { name: 'Staff' }).click()
  await expect(page.getByRole('button', { name: /Someone With A Considerably/ })).toBeVisible()
  await noSideways(page)

  await page.getByRole('button', { name: 'Approval chains' }).click()
  await page.getByLabel('Department').selectOption('d1')
  await expect(page.getByText('No approval chain for DEFAULT.')).toBeVisible()
  await noSideways(page)
})

test('organisation: controls are large enough to tap', async ({ page }) => {
  await signedIn(page, FULL)
  await page.goto('/administration/organisation')
  for (const name of ['Chart', 'Departments', 'Positions', 'Staff', 'Approval chains']) {
    const box = await page.getByRole('button', { name }).boundingBox()
    expect(box!.height, name).toBeGreaterThanOrEqual(40)
  }
})

test('organisation: link and screen follow permissions', async ({ page }) => {
  await signedIn(page, { administration: { VIEW: 'ALL' } })
  await page.goto('/administration/organisation')
  await expect(page.getByRole('heading', { name: 'Organisation' })).toBeVisible()
  const menu = page.getByRole('button', { name: 'Open navigation' })
  if (await menu.isVisible()) await menu.click()
  await expect(page.getByRole('link', { name: 'Organisation' })).toBeVisible()
  await page.getByRole('link', { name: 'Organisation' }).click() // also closes the phone menu
  await page.getByRole('button', { name: 'Staff' }).click()
  await page.getByRole('button', { name: /Someone With A Considerably/ }).click()
  await expect(page.getByText(/look at assignments but not change/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'End assignment' })).toHaveCount(0)
})

test('organisation: no access shows a refusal, not the screen', async ({ page }) => {
  await signedIn(page, { finance: { VIEW: 'ALL' } })
  await page.goto('/administration/organisation')
  await expect(page.getByRole('heading', { name: 'Organisation' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Organisation' })).toHaveCount(0)
})
