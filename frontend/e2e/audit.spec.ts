import { expect, test, type Page } from '@playwright/test'

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

const rows = Array.from({ length: 6 }, (_, index) => ({
  id: 100 - index,
  occurred_at: '2026-11-20T04:12:00Z',
  actor_id: null,
  actor_username: 'a-person-with-a-rather-long-username@example.org',
  event_type: 'PERMISSION_CHANGED',
  object_type: 'rbac.Role',
  object_id: '6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11',
  success: index % 3 !== 0,
  ip_address: '10.0.0.5',
  request_id: 'req-12345678',
}))

async function signedIn(page: Page, permissions: object) {
  await page.route('**/api/v1/auth/me/', (route) =>
    route.fulfill(
      json({
        user: {
          id: '6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11',
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
  await page.route('**/api/v1/audit/event-types/', (route) =>
    route.fulfill(json({ results: ['LOGIN_FAILED', 'PERMISSION_CHANGED'] })),
  )
  await page.route('**/api/v1/audit/events/', (route) =>
    route.fulfill(json({ count: rows.length, next: null, previous: null, results: rows })),
  )
  await page.route('**/api/v1/audit/events/100/', (route) =>
    route.fulfill(
      json({
        ...rows[0],
        user_agent: 'Mozilla/5.0',
        changes: { added: ['finance.VIEW: ALL'] },
        metadata: {},
        department_id: null,
        prev_hash: 'a'.repeat(64),
        event_hash: 'b'.repeat(64),
      }),
    ),
  )
}

async function noSideways(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

test('audit log: readable at every width, details open, no sideways scrolling', async ({
  page,
}) => {
  await signedIn(page, { audit: { VIEW: 'ALL' } })
  await page.goto('/administration/audit')
  await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible()
  await expect(page.getByText('6 events')).toBeVisible()
  await noSideways(page)

  const width = page.viewportSize()!.width
  const header = page.getByRole('columnheader', { name: 'When' })
  if (width >= 900) await expect(header).toBeVisible()
  else await expect(header).toBeHidden() // small screens show one card per event instead

  await page.getByRole('button', { name: 'Show details of event 100' }).click()
  await expect(page.getByText('finance.VIEW: ALL')).toBeVisible()
  await noSideways(page)

  const apply = page.getByRole('button', { name: 'Apply filters' })
  const box = await apply.boundingBox()
  expect(box!.height).toBeGreaterThanOrEqual(40)
})

test('audit log link and export button follow permissions', async ({ page }) => {
  await signedIn(page, { audit: { VIEW: 'ALL' } })
  await page.goto('/administration/audit')
  await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Export CSV' })).toHaveCount(0)

  const menu = page.getByRole('button', { name: 'Open navigation' })
  if (await menu.isVisible()) await menu.click()
  await expect(page.getByRole('link', { name: 'Audit log' })).toBeVisible()
})

test('someone without audit access sees a refusal, not the log', async ({ page }) => {
  await signedIn(page, { finance: { VIEW: 'ALL' } })
  await page.goto('/administration/audit')
  await expect(page.getByRole('heading', { name: 'Audit log' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Audit log' })).toHaveCount(0)
})
