import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { ME, NOT_SIGNED_IN, USER, SESSION, apiError, mockApi } from '../../test/mockApi'
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

afterEach(() => vi.unstubAllGlobals())

describe('route protection', () => {
  it('sends an anonymous visitor to the sign-in page and shows no system content', async () => {
    mockApi({ 'GET /auth/me/': NOT_SIGNED_IN })
    renderAt('/modules/financial-management')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument()
  })

  it('shows a retry when the server cannot be reached, not the sign-in page', async () => {
    mockApi({ 'GET /auth/me/': apiError(503, 'unavailable', 'Down.') })
    renderAt()

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the server')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('forces a user with a temporary password to the account page', async () => {
    mockApi({
      'GET /auth/me/': {
        body: {
          user: { ...USER, must_change_password: true },
          session: SESSION,
        },
      },
      'GET /auth/sessions/': { body: { results: [] } },
    })
    renderAt('/')

    expect(await screen.findByRole('heading', { name: 'My account' })).toBeInTheDocument()
    expect(screen.getByText(/must choose a new password/i)).toBeInTheDocument()
  })

  it('returns to the sign-in page with a notice when the session ends mid-use', async () => {
    const user = userEvent.setup()
    let signedIn = true
    mockApi({
      'GET /auth/me/': () => (signedIn ? ME : NOT_SIGNED_IN),
      'GET /health/': () => (signedIn ? HEALTH : NOT_SIGNED_IN),
      'GET /auth/sessions/': () => (signedIn ? { body: { results: [] } } : NOT_SIGNED_IN),
    })
    renderAt('/')
    await screen.findByRole('heading', { name: 'Dashboard' })

    signedIn = false // e.g. signed out from another device, or timed out
    await user.click(screen.getByRole('link', { name: 'Alice Mwangi' }))

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Your session has ended')
  })
})

describe('sign in and sign out', () => {
  it('signs in with the typed credentials and opens the dashboard', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      'GET /auth/me/': NOT_SIGNED_IN,
      'POST /auth/login/': ME,
      'GET /health/': HEALTH,
    })
    renderAt()

    await user.type(await screen.findByLabelText('Username'), '  alice ')
    await user.type(screen.getByLabelText('Password'), 'correct-horse-battery-9')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    const login = calls.find((call) => call.path === '/auth/login/')!
    expect(login.body).toEqual({
      username: 'alice',
      password: 'correct-horse-battery-9',
    })
    expect(login.headers.get('X-CSRFToken')).toBe('test-token')
  })

  it('shows the server message and clears the password after a failed sign-in', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /auth/me/': NOT_SIGNED_IN,
      'POST /auth/login/': apiError(401, 'invalid_credentials', 'Invalid username or password.'),
    })
    renderAt()

    await user.type(await screen.findByLabelText('Username'), 'alice')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByLabelText('Username')).toHaveValue('alice')
  })

  it('shows the lockout message', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /auth/me/': NOT_SIGNED_IN,
      'POST /auth/login/': apiError(429, 'too_many_attempts', 'Too many failed sign-in attempts.'),
    })
    renderAt()

    await user.type(await screen.findByLabelText('Username'), 'alice')
    await user.type(screen.getByLabelText('Password'), 'x')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many failed sign-in attempts.')
  })

  it('does not allow submitting an empty form', async () => {
    mockApi({ 'GET /auth/me/': NOT_SIGNED_IN })
    renderAt()

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeDisabled()
  })

  it('signs out through the server and returns to the sign-in page', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      'GET /auth/me/': ME,
      'GET /health/': HEALTH,
      'POST /auth/logout/': { status: 204 },
    })
    renderAt()

    await user.click(await screen.findByRole('button', { name: 'Sign out' }))

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    const logout = calls.find((call) => call.path === '/auth/logout/')!
    expect(logout.headers.get('X-CSRFToken')).toBe('test-token')
  })

  it('keeps nothing about the user in browser storage', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /auth/me/': NOT_SIGNED_IN,
      'POST /auth/login/': ME,
      'GET /health/': HEALTH,
    })
    renderAt()

    await user.type(await screen.findByLabelText('Username'), 'alice')
    await user.type(screen.getByLabelText('Password'), 'correct-horse-battery-9')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('heading', { name: 'Dashboard' })

    await waitFor(() => {
      expect(localStorage.length).toBe(0)
      expect(sessionStorage.length).toBe(0)
    })
  })
})
