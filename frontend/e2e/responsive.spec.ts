import { expect, test } from '@playwright/test'

// Wide layout (permanent sidebar) starts at 900px, see src/index.css.
const WIDE_BREAKPOINT = 900

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/auth/me/', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
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
      }),
    }),
  )
  await page.route('**/api/v1/health/', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', database: 'ok' }),
    }),
  )
})

test('layout adapts to the viewport and never scrolls sideways', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  const width = page.viewportSize()!.width
  const navLink = page.getByRole('link', { name: 'Financial Management' })
  const menuButton = page.getByRole('button', { name: /navigation/i })

  if (width >= WIDE_BREAKPOINT) {
    await expect(navLink).toBeVisible()
    await expect(menuButton).toBeHidden()
  } else {
    await expect(navLink).toBeHidden()
    await expect(menuButton).toBeVisible()

    await menuButton.click()
    await expect(navLink).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(navLink).toBeHidden()
  }

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})

test('navigating to a module shows the not-yet-available notice', async ({ page }) => {
  await page.goto('/')

  const width = page.viewportSize()!.width
  if (width < WIDE_BREAKPOINT) {
    await page.getByRole('button', { name: 'Open navigation' }).click()
  }
  await page.getByRole('link', { name: 'Stores and Inventory' }).click()

  await expect(page.getByRole('heading', { name: 'Stores and Inventory' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('Not yet available.')
})
