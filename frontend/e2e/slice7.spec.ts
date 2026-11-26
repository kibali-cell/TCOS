import { expect, test, type Page } from '@playwright/test'

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})
const USER = {
  id: 'u1',
  username: 'alice',
  full_name: 'Alice Mwangi',
  email: 'alice@example.org',
  phone: '',
  status: 'ACTIVE',
  must_change_password: false,
  last_login: '2026-11-19T20:00:00Z',
}
const SESSION = { idle_expires_at: null, absolute_expires_at: '2026-11-20T15:00:00Z' }
const NOT_SIGNED_IN = { error: { code: 'not_authenticated', message: 'x', details: null } }
const LONG_NAME =
  'a-very-long-file-name-for-a-quarterly-supplier-invoice-and-delivery-note-2026.pdf'

async function noSideways(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

async function base(page: Page) {
  await page.route('**/api/v1/csrf/', (route) => route.fulfill(json({ detail: 'ok' })))
  await page
    .context()
    .addCookies([{ name: 'csrftoken', value: 'test-token', url: 'http://localhost:5173' }])
}

test('forgot-password page fits and gives one answer', async ({ page }) => {
  await base(page)
  await page.route('**/api/v1/auth/me/', (route) => route.fulfill(json(NOT_SIGNED_IN, 401)))
  await page.route('**/api/v1/auth/password/forgot/', (route) =>
    route.fulfill(json({ detail: 'If that account exists, a reset link is on its way.' }, 202)),
  )
  await page.goto('/forgot-password')
  await noSideways(page)
  await page.getByLabel('Username or e-mail').fill('someone')
  await page.getByRole('button', { name: 'Send reset link' }).click()
  await expect(page.getByRole('status')).toContainText('If that account exists')
  await noSideways(page)
})

test('reset page removes the token from the address bar and fits', async ({ page }) => {
  await base(page)
  await page.route('**/api/v1/auth/me/', (route) => route.fulfill(json(NOT_SIGNED_IN, 401)))
  await page.goto('/reset-password#token=secret-token-value')
  await expect(page.getByLabel('New password', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/reset-password$/)
  expect(page.url()).not.toContain('secret-token-value')
  await noSideways(page)
  const box = await page.getByRole('button', { name: 'Set new password' }).boundingBox()
  expect(box!.height).toBeGreaterThanOrEqual(44)
})

test('sign-in second step fits and is usable by touch', async ({ page }) => {
  await base(page)
  await page.route('**/api/v1/auth/me/', (route) => route.fulfill(json(NOT_SIGNED_IN, 401)))
  await page.route('**/api/v1/auth/login/', (route) =>
    route.fulfill(json({ two_factor_required: true })),
  )
  await page.goto('/login')
  await page.getByLabel('Username').fill('alice')
  await page.getByLabel('Password').fill('correct-horse-battery-9')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Second step' })).toBeVisible()
  await noSideways(page)
  const box = await page.getByRole('button', { name: 'Verify' }).boundingBox()
  expect(box!.height).toBeGreaterThanOrEqual(44)
})

test('two-factor set-up on the account page fits with the QR code and key', async ({ page }) => {
  await base(page)
  await page.route('**/api/v1/auth/me/', (route) =>
    route.fulfill(json({ user: USER, session: SESSION })),
  )
  await page.route('**/api/v1/auth/sessions/', (route) => route.fulfill(json({ results: [] })))
  await page.route('**/api/v1/health/', (route) =>
    route.fulfill(json({ status: 'ok', database: 'ok' })),
  )
  await page.route('**/api/v1/approvals/summary/', (route) =>
    route.fulfill(json({ pending: 0, unread_notifications: 0 })),
  )
  await page.route('**/api/v1/auth/2fa/', (route) =>
    route.fulfill(
      json({ enabled: false, required: false, setup_required: false, recovery_codes_left: 0 }),
    ),
  )
  const qr =
    'data:image/svg+xml;base64,' +
    Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>').toString(
      'base64',
    )
  await page.route('**/api/v1/auth/2fa/enrol/', (route) =>
    route.fulfill(
      json({ secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/x', qr }),
    ),
  )
  await page.route('**/api/v1/auth/2fa/confirm/', (route) =>
    route.fulfill(
      json({ recovery_codes: Array.from({ length: 10 }, (_, i) => `ABCD${i}-EFGH${i}`) }),
    ),
  )
  await page.goto('/account')
  await page.getByRole('button', { name: 'Set up two-factor sign-in' }).click()
  await expect(page.getByAltText('QR code for your authenticator app')).toBeVisible()
  await noSideways(page)
  await page.getByLabel(/Enter the 6-digit code/).fill('123456')
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByRole('list', { name: 'Recovery codes' })).toBeVisible()
  await noSideways(page)
})

test('attachments on a request fit, even with long file names', async ({ page }) => {
  await base(page)
  const me = {
    user: USER,
    session: SESSION,
    permissions: { approvals: { VIEW: 'ALL', CREATE: 'ALL' } },
    roles: [],
  }
  await page.route('**/api/v1/auth/me/', (route) => route.fulfill(json(me)))
  await page.route('**/api/v1/health/', (route) =>
    route.fulfill(json({ status: 'ok', database: 'ok' })),
  )
  await page.route('**/api/v1/approvals/summary/', (route) =>
    route.fulfill(json({ pending: 0, unread_notifications: 0 })),
  )
  await page.route('**/api/v1/approvals/requests/r1/', (route) =>
    route.fulfill(
      json({
        id: 'r1',
        request_number: 'TCOS-REQ-2026-000001',
        request_type: 'GENERAL',
        type_label: 'General request',
        title: 'Buy school books',
        status: 'DRAFT',
        risk_level: 'LOW',
        amount_tzs: 150000,
        requester: { id: 'u1', name: 'Alice Mwangi' },
        department: { id: 'd1', name: 'Finance' },
        current_step: 0,
        waiting_for: [],
        submitted_at: null,
        decided_at: null,
        created_at: '2026-11-20T03:00:00Z',
        can: {
          edit: true,
          submit: true,
          cancel: true,
          review: false,
          approve: false,
          reject: false,
          comment: false,
        },
        description: 'Term 1',
        decision_comment: '',
        payload: { kind: '', kind_label: '' },
        version: 1,
        needs_password: false,
        route: [],
        history: [],
        can_attach_files: true,
        attachments: [
          {
            id: 'd1',
            name: LONG_NAME,
            content_type: 'application/pdf',
            size_bytes: 123456,
            classification: 'CONFIDENTIAL',
            scan_status: 'NOT_SCANNED',
            uploaded_by: 'Alice Mwangi',
            uploaded_at: '2026-11-20T04:00:00Z',
            can_archive: true,
          },
        ],
      }),
    ),
  )
  await page.goto('/approvals/r1')
  await expect(page.getByRole('heading', { name: 'Attachments' })).toBeVisible()
  await expect(page.getByRole('button', { name: `Download ${LONG_NAME}` })).toBeVisible()
  await noSideways(page)
  const box = await page.getByRole('button', { name: `Download ${LONG_NAME}` }).boundingBox()
  expect(box!.height).toBeGreaterThanOrEqual(44)
})
