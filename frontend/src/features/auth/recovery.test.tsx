import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { ME, NOT_SIGNED_IN, apiError, mockApi } from '../../test/mockApi'
import { AuthProvider } from './AuthContext'

function renderAt(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const HEALTH = { body: { status: 'ok', database: 'ok' } }
const SUMMARY = { body: { pending: 0, unread_notifications: 0 } }
const TWO_FACTOR_OFF = {
  enabled: false,
  required: false,
  setup_required: false,
  recovery_codes_left: 0,
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

describe('two-factor sign-in step', () => {
  function signInRoutes(reply: () => { status?: number; body?: unknown }) {
    let signedIn = false
    return mockApi({
      'GET /auth/me/': () => (signedIn ? ME : NOT_SIGNED_IN),
      'POST /auth/login/': { body: { two_factor_required: true } },
      'POST /auth/login/2fa/': () => {
        const result = reply()
        if (!result.status || result.status < 300) signedIn = true
        return result.status ? result : ME
      },
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
    })
  }

  async function passwordStep() {
    renderAt('/login')
    await userEvent.type(await screen.findByLabelText('Username'), 'alice')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse-battery-9')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  }

  it('asks for the code after the password and then signs in', async () => {
    const { calls } = signInRoutes(() => ({}))
    await passwordStep()
    expect(await screen.findByRole('heading', { name: 'Second step' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Authenticator code'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/login/2fa/')?.body).toEqual({
      code: '123456',
      recovery: false,
    })
  })

  it('accepts a recovery code', async () => {
    const { calls } = signInRoutes(() => ({}))
    await passwordStep()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Use a recovery code instead' }),
    )
    await userEvent.type(screen.getByLabelText('Recovery code'), 'ABCDE-FGHJK')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    await screen.findByRole('heading', { name: 'Dashboard' })
    expect(calls.find((c) => c.path === '/auth/login/2fa/')?.body).toMatchObject({ recovery: true })
  })

  it('shows a wrong code, clears the field and stays on the step', async () => {
    signInRoutes(() => apiError(401, 'invalid_credentials', 'That code is not right.'))
    await passwordStep()
    await userEvent.type(await screen.findByLabelText('Authenticator code'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not right.')
    expect(screen.getByLabelText('Authenticator code')).toHaveValue('')
  })

  it('goes back to the password step when the first step has expired', async () => {
    signInRoutes(() =>
      apiError(401, 'invalid_credentials', 'Start again: enter your username and password.'),
    )
    await passwordStep()
    await userEvent.type(await screen.findByLabelText('Authenticator code'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })
})

describe('required two-factor set-up', () => {
  it('sends a person who must set it up to the account page', async () => {
    mockApi({
      'GET /auth/me/': {
        body: {
          ...ME.body,
          two_factor: {
            enabled: false,
            required: true,
            setup_required: true,
            recovery_codes_left: 0,
          },
        },
      },
      'GET /auth/2fa/': {
        body: { enabled: false, required: true, setup_required: true, recovery_codes_left: 0 },
      },
      'GET /auth/sessions/': { body: { results: [] } },
    })
    renderAt('/')
    expect(await screen.findByRole('heading', { name: 'My account' })).toBeInTheDocument()
    expect(await screen.findByText(/is required for your account or role/i)).toBeInTheDocument()
  })

  it('walks through enrolment and shows the recovery codes once', async () => {
    let enabled = false
    const { calls } = mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [] } },
      'GET /auth/2fa/': () => ({
        body: { ...TWO_FACTOR_OFF, enabled, recovery_codes_left: enabled ? 10 : 0 },
      }),
      'POST /auth/2fa/enrol/': {
        body: {
          secret: 'JBSWY3DPEHPK3PXP',
          otpauth_uri: 'otpauth://totp/x',
          qr: 'data:image/svg+xml;base64,PHN2Zy8+',
        },
      },
      'POST /auth/2fa/confirm/': () => {
        enabled = true
        return { body: { recovery_codes: ['AAAAA-BBBBB', 'CCCCC-DDDDD'] } }
      },
    })
    renderAt('/account')
    await userEvent.click(await screen.findByRole('button', { name: 'Set up two-factor sign-in' }))
    expect(await screen.findByAltText('QR code for your authenticator app')).toBeInTheDocument()
    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Enter the 6-digit code/), '654321')
    await userEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    expect(await screen.findByText('AAAAA-BBBBB')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/2fa/confirm/')?.body).toEqual({ code: '654321' })
    await userEvent.click(screen.getByRole('button', { name: 'I have saved them' }))
    expect(screen.queryByText('AAAAA-BBBBB')).not.toBeInTheDocument()
    expect(await screen.findByText(/Two-factor sign-in is on/)).toBeInTheDocument()
  })

  it('needs password and code to turn it off, and cannot when it is required', async () => {
    mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [] } },
      'GET /auth/2fa/': {
        body: { enabled: true, required: true, setup_required: false, recovery_codes_left: 8 },
      },
    })
    renderAt('/account')
    expect(await screen.findByText(/cannot be turned off/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Turn off' })).not.toBeInTheDocument()
  })

  it('turns it off after re-authentication and shows a wrong-code error', async () => {
    let attempts = 0
    const { calls } = mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [] } },
      'GET /auth/2fa/': {
        body: { enabled: true, required: false, setup_required: false, recovery_codes_left: 8 },
      },
      'POST /auth/2fa/disable/': () => {
        attempts += 1
        return attempts === 1
          ? apiError(400, 'validation_error', 'Invalid.', { code: ['That code is not right.'] })
          : { body: TWO_FACTOR_OFF }
      },
    })
    renderAt('/account')
    await userEvent.click(await screen.findByRole('button', { name: 'Turn off' }))
    await userEvent.type(screen.getByLabelText('Your password'), 'correct-horse-battery-9')
    await userEvent.type(screen.getByLabelText(/Current code/), '111111')
    await userEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not right.')
    expect(calls.filter((c) => c.path === '/auth/2fa/disable/')).toHaveLength(1)
  })
})

describe('forgot and reset password', () => {
  it('shows the same confirmation for any identifier', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': NOT_SIGNED_IN,
      'POST /auth/password/forgot/': {
        status: 202,
        body: { detail: 'If that account exists, a reset link is on its way.' },
      },
    })
    renderAt('/login')
    await userEvent.click(await screen.findByRole('link', { name: 'Forgot your password?' }))
    await userEvent.type(await screen.findByLabelText('Username or e-mail'), 'nobody')
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/If that account exists/)
    expect(calls.find((c) => c.path === '/auth/password/forgot/')?.body).toEqual({
      identifier: 'nobody',
    })
  })

  it('reads the token from the address fragment, removes it, and sets the password', async () => {
    window.history.replaceState(null, '', '/reset-password#token=abc123')
    const { calls } = mockApi({
      'GET /auth/me/': NOT_SIGNED_IN,
      'POST /auth/password/reset/': { body: { detail: 'Your password has been changed.' } },
    })
    renderAt('/reset-password')
    await userEvent.type(await screen.findByLabelText('New password'), 'a-brand-new-passphrase-42')
    await userEvent.type(screen.getByLabelText('Repeat new password'), 'a-brand-new-passphrase-42')
    await userEvent.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByText(/Your password has been changed/)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/password/reset/')?.body).toEqual({
      token: 'abc123',
      new_password: 'a-brand-new-passphrase-42',
    })
    expect(window.location.hash).toBe('')
    expect(screen.getByRole('link', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('refuses mismatched passwords without calling the server', async () => {
    window.history.replaceState(null, '', '/reset-password#token=abc123')
    const { calls } = mockApi({ 'GET /auth/me/': NOT_SIGNED_IN })
    renderAt('/reset-password')
    await userEvent.type(await screen.findByLabelText('New password'), 'a-brand-new-passphrase-42')
    await userEvent.type(screen.getByLabelText('Repeat new password'), 'something-else-entirely-1')
    await userEvent.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByText('The two passwords do not match.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/password/reset/')).toBe(false)
  })

  it('says a bad or used link is bad and offers a new one', async () => {
    window.history.replaceState(null, '', '/reset-password#token=old')
    mockApi({
      'GET /auth/me/': NOT_SIGNED_IN,
      'POST /auth/password/reset/': apiError(400, 'validation_error', 'Invalid.', {
        token: ['This link is not valid or has expired. Ask for a new one.'],
      }),
    })
    renderAt('/reset-password')
    await userEvent.type(await screen.findByLabelText('New password'), 'a-brand-new-passphrase-42')
    await userEvent.type(screen.getByLabelText('Repeat new password'), 'a-brand-new-passphrase-42')
    await userEvent.click(screen.getByRole('button', { name: 'Set new password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/not valid or has expired/)
    expect(screen.getByRole('link', { name: 'Ask for a new link' })).toBeInTheDocument()
  })

  it('shows a clear message when the link has no token', async () => {
    mockApi({ 'GET /auth/me/': NOT_SIGNED_IN })
    renderAt('/reset-password')
    expect(await screen.findByRole('alert')).toHaveTextContent(/not complete/)
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
  })
})
