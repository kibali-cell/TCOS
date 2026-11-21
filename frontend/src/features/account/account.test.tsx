import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { AuthProvider } from '../auth/AuthContext'
import { ME, apiError, mockApi } from '../../test/mockApi'

const LAPTOP = {
  id: 'a1111111-1111-4111-8111-111111111111',
  device_label: 'Chrome on Windows',
  ip_address: '10.0.0.5',
  created_at: '2026-11-20T04:00:00Z',
  last_seen_at: '2026-11-20T04:10:00Z',
  is_current: true,
}
const PHONE = {
  id: 'b2222222-2222-4222-8222-222222222222',
  device_label: 'Safari on iPhone',
  ip_address: '10.0.0.9',
  created_at: '2026-11-19T10:00:00Z',
  last_seen_at: '2026-11-19T12:00:00Z',
  is_current: false,
}

function renderAccount() {
  return render(
    <MemoryRouter initialEntries={['/account']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('devices', () => {
  it('lists devices, marks this one, and offers sign out only for the others', async () => {
    mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [LAPTOP, PHONE] } },
    })
    renderAccount()

    const list = await screen.findByRole('list', { name: 'Signed-in devices' })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText('This device')).toBeInTheDocument()
    expect(within(items[0]).queryByRole('button')).not.toBeInTheDocument()
    expect(
      within(items[1]).getByRole('button', {
        name: /Sign out Safari on iPhone/,
      }),
    ).toBeVisible()
  })

  it('signs out one other device and refreshes the list', async () => {
    const user = userEvent.setup()
    let phoneActive = true
    const { calls } = mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': () => ({
        body: { results: phoneActive ? [LAPTOP, PHONE] : [LAPTOP] },
      }),
      [`DELETE /auth/sessions/${PHONE.id}/`]: () => {
        phoneActive = false
        return { status: 204 }
      },
    })
    renderAccount()

    await user.click(await screen.findByRole('button', { name: /Sign out Safari on iPhone/ }))

    expect(await screen.findByText('That device was signed out.')).toBeInTheDocument()
    expect(screen.queryByText('Safari on iPhone')).not.toBeInTheDocument()
    expect(calls.find((c) => c.method === 'DELETE')!.headers.get('X-CSRFToken')).toBe('test-token')
  })

  it('"Sign out all other devices" reports how many were signed out', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [LAPTOP, PHONE] } },
      'POST /auth/sessions/end-others/': { body: { ended: 1 } },
    })
    renderAccount()

    await user.click(await screen.findByRole('button', { name: 'Sign out all other devices' }))

    expect(await screen.findByText('1 other device was signed out.')).toBeInTheDocument()
  })

  it('disables "Sign out all other devices" when there are no other devices', async () => {
    mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [LAPTOP] } },
    })
    renderAccount()

    await screen.findByText('This device')
    expect(screen.getByRole('button', { name: 'Sign out all other devices' })).toBeDisabled()
  })

  it('shows an error when devices cannot be loaded', async () => {
    mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': apiError(500, 'server_error', 'Boom.'),
    })
    renderAccount()

    expect(await screen.findByText('Could not load your devices.')).toBeInTheDocument()
  })
})

describe('change password', () => {
  async function fill(
    user: ReturnType<typeof userEvent.setup>,
    current: string,
    next: string,
    again: string,
  ) {
    await user.type(await screen.findByLabelText('Current password'), current)
    await user.type(screen.getByLabelText('New password'), next)
    await user.type(screen.getByLabelText('Repeat new password'), again)
    await user.click(screen.getByRole('button', { name: 'Change password' }))
  }

  it('does not call the server when the two new passwords differ', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [LAPTOP] } },
    })
    renderAccount()

    await fill(user, 'old-password-123', 'a-brand-new-passphrase-42', 'something-else-entirely')

    expect(await screen.findByText('The two new passwords do not match.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/password/change/')).toBe(false)
  })

  it("shows the server's reasons next to the field", async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [LAPTOP] } },
      'POST /auth/password/change/': apiError(400, 'validation_error', 'Invalid.', {
        new_password: ['This password is too common.'],
      }),
    })
    renderAccount()

    await fill(user, 'old-password-123', 'password1234', 'password1234')

    expect(await screen.findByText('This password is too common.')).toBeInTheDocument()
  })

  it('confirms success, clears the fields and mentions other devices', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi({
      'GET /auth/me/': ME,
      'GET /auth/sessions/': { body: { results: [LAPTOP] } },
      'POST /auth/password/change/': { body: { ended_other_sessions: 2 } },
    })
    renderAccount()

    await fill(user, 'old-password-123', 'a-brand-new-passphrase-42', 'a-brand-new-passphrase-42')

    expect(
      await screen.findByText(/Password changed\. 2 other device\(s\) were signed out\./),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Current password')).toHaveValue('')
    expect(calls.find((c) => c.path === '/auth/password/change/')!.body).toEqual({
      current_password: 'old-password-123',
      new_password: 'a-brand-new-passphrase-42',
    })
  })
})
