import { expect, test, type Page } from '@playwright/test'

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

const MODULES = [
  ['administration', 'Institutional Administration'],
  ['social_welfare', 'Social Welfare Management'],
  ['children', 'Child Profile Management'],
  ['education', 'Education Management'],
  ['medical', 'Medical Management'],
  ['finance', 'Financial Management'],
  ['projects', 'Project Management'],
  ['hr', 'Human Resources'],
  ['procurement', 'Procurement'],
  ['stores', 'Stores and Inventory'],
  ['donors', 'Donor Management'],
  ['reports', 'Reports and Analytics'],
  ['approvals', 'Approval Centre'],
  ['audit', 'Audit Log'],
  ['users', 'Users, Roles and Permissions'],
]
const CATALOGUE = {
  modules: MODULES.map(([code, name]) => ({ code, name })),
  actions: ['VIEW', 'CREATE', 'EDIT', 'DELETE', 'APPROVE', 'REJECT', 'EXPORT', 'MANAGE_USERS'],
  scopes: ['ALL', 'DEPARTMENT', 'OWN', 'ASSIGNED'],
}
const ROLE = {
  id: 'a1111111-1111-4111-8111-111111111111',
  code: 'STOREKEEPER',
  name: 'Storekeeper',
  description: 'Stores and inventory.',
  is_system: true,
  is_active: true,
}

async function mockSignedInAdmin(page: Page, permissions: object) {
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
}

async function noSideways(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

test('roles screen: pick a role, see the whole matrix, no sideways scrolling', async ({ page }) => {
  await mockSignedInAdmin(page, { users: { VIEW: 'ALL', MANAGE_USERS: 'ALL' } })
  await page.route('**/api/v1/rbac/catalogue/', (route) => route.fulfill(json(CATALOGUE)))
  await page.route('**/api/v1/rbac/roles/', (route) =>
    route.fulfill(json({ results: [{ ...ROLE, holders: 2 }] })),
  )
  await page.route(`**/api/v1/rbac/roles/${ROLE.id}/`, (route) =>
    route.fulfill(json({ ...ROLE, grants: [{ module: 'stores', action: 'VIEW', scope: 'ALL' }] })),
  )

  await page.goto('/administration/roles')
  await expect(page.getByRole('heading', { name: 'Roles and permissions' })).toBeVisible()
  await noSideways(page)

  await page.getByRole('button', { name: /Storekeeper/ }).click()
  const storesView = page.getByRole('combobox', { name: 'Stores and Inventory: View' })
  await expect(storesView).toHaveValue('ALL')
  await expect(page.getByRole('combobox')).toHaveCount(15 * 8)
  await noSideways(page)

  // Every selector is big enough to use with a thumb.
  const box = await storesView.boundingBox()
  expect(box!.height).toBeGreaterThanOrEqual(36)
  expect(box!.width).toBeGreaterThanOrEqual(60)

  await page.getByRole('combobox', { name: 'Financial Management: Edit' }).scrollIntoViewIfNeeded()
  await page
    .getByRole('combobox', { name: 'Financial Management: Edit' })
    .selectOption('DEPARTMENT')
  const save = page.getByRole('button', { name: 'Save permissions' })
  await expect(save).toBeEnabled()
  await expect(save).toBeInViewport() // the save bar stays reachable while scrolling a long matrix
  await noSideways(page)
})

test('navigation shows only the modules this person may view', async ({ page }) => {
  await mockSignedInAdmin(page, { finance: { VIEW: 'ALL' } })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  // On narrow screens the navigation is a drawer.
  const menu = page.getByRole('button', { name: 'Open navigation' })
  if (await menu.isVisible()) await menu.click()

  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav.getByRole('link')).toHaveText(['Dashboard', 'Financial Management'])
  await noSideways(page)
})

test('a module address without permission shows a refusal', async ({ page }) => {
  await mockSignedInAdmin(page, { finance: { VIEW: 'ALL' } })
  await page.goto('/modules/medical')
  await expect(page.getByRole('heading', { name: 'No access' })).toBeVisible()
  await noSideways(page)
})
