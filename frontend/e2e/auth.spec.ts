import { expect, test, type Page } from '@playwright/test'

const USER = {
  id: '6f1ad6c0-5c1e-4b8a-9d57-3f2a2f0e6b11',
  username: 'alice',
  full_name: 'Alice Mwangi',
  email: 'alice@example.org',
  phone: '',
  status: 'ACTIVE',
  must_change_password: false,
  last_login: '2026-11-19T20:00:00Z',
}
const SESSION = { idle_expires_at: null, absolute_expires_at: '2026-11-20T15:00:00Z' }
const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

async function noSideways(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

test('anonymous visitor sees a usable sign-in page that fits the screen', async ({ page }) => {
  await page.route('**/api/v1/auth/me/', (route) =>
    route.fulfill(
      json(
        { error: { code: 'not_authenticated', message: 'Sign in required.', details: null } },
        401,
      ),
    ),
  )
  await page.goto('/some/protected/page')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Financial Management' })).toHaveCount(0)
  await noSideways(page)

  const box = await page.getByRole('button', { name: 'Sign in' }).boundingBox()
  expect(box!.height).toBeGreaterThanOrEqual(44) // comfortable touch target
})

test('sign in, see the account page and devices, then sign out', async ({ page }) => {
  let signedIn = false
  await page.route('**/api/v1/csrf/', (route) => route.fulfill(json({ detail: 'ok' })))
  await page
    .context()
    .addCookies([{ name: 'csrftoken', value: 'test-token', url: 'http://localhost:5173' }])
  await page.route('**/api/v1/auth/me/', (route) =>
    route.fulfill(
      signedIn
        ? json({ user: USER, session: SESSION })
        : json({ error: { code: 'not_authenticated', message: 'x', details: null } }, 401),
    ),
  )
  await page.route('**/api/v1/auth/login/', (route) => {
    signedIn = true
    return route.fulfill(json({ user: USER, session: SESSION }))
  })
  await page.route('**/api/v1/auth/logout/', (route) => {
    signedIn = false
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/v1/health/', (route) =>
    route.fulfill(json({ status: 'ok', database: 'ok' })),
  )
  await page.route('**/api/v1/auth/sessions/', (route) =>
    route.fulfill(
      json({
        results: [
          {
            id: 'a1111111-1111-4111-8111-111111111111',
            device_label: 'Chrome on Windows',
            ip_address: '10.0.0.5',
            created_at: '2026-11-20T04:00:00Z',
            last_seen_at: '2026-11-20T04:10:00Z',
            is_current: true,
          },
          {
            id: 'b2222222-2222-4222-8222-222222222222',
            device_label: 'Safari on iPhone',
            ip_address: '10.0.0.9',
            created_at: '2026-11-19T10:00:00Z',
            last_seen_at: '2026-11-19T12:00:00Z',
            is_current: false,
          },
        ],
      }),
    ),
  )

  await page.goto('/')
  await page.getByLabel('Username').fill('alice')
  await page.getByLabel('Password').fill('correct-horse-battery-9')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  await page.getByRole('link', { name: 'Alice Mwangi' }).click()
  await expect(page.getByRole('heading', { name: 'My account' })).toBeVisible()
  await expect(page.getByText('This device')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign out all other devices' })).toBeVisible()
  await noSideways(page)

  // Nothing about the user is written to browser storage.
  const stored = await page.evaluate(() => localStorage.length + sessionStorage.length)
  expect(stored).toBe(0)

  await page.getByRole('button', { name: 'Sign out', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})
