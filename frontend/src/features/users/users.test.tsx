import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { AuthProvider } from '../auth/AuthContext'
import { apiError, meAs, mockApi } from '../../test/mockApi'
import type { DashboardData } from '../dashboard/types'
import type { UserRow } from './types'

const HEALTH = { body: { status: 'ok', database: 'ok' } }
const SUMMARY = { body: { pending: 0, unread_notifications: 0 } }
const MANAGER = meAs({ users: { VIEW: 'ALL', MANAGE_USERS: 'ALL' } })
const VIEWER = meAs({ users: { VIEW: 'ALL' } })

function row(overrides: Partial<UserRow> = {}): UserRow {
  return {
    id: 'u1',
    username: 'alice',
    full_name: 'Alice Mwangi',
    email: 'alice@example.org',
    phone: '',
    status: 'ACTIVE',
    department: { id: 'd1', name: 'Finance' },
    position: 'Accountant',
    roles: [{ id: 'a1', role_id: 'r1', name: 'Finance Officer', department: null }],
    created_at: '2026-11-01T08:00:00Z',
    last_login: null,
    must_change_password: false,
    ...overrides,
  }
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

const PAGE = { body: { count: 1, next: null, previous: null, results: [row()] } }

describe('users', () => {
  it('lists users with their department, position and roles', async () => {
    mockApi({
      'GET /auth/me/': MANAGER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /users/?ordering=full_name&page=1': PAGE,
    })
    renderAt('/administration/users')
    const table = await screen.findByRole('table', { name: 'Users' })
    expect(within(table).getByRole('link', { name: 'Alice Mwangi' })).toHaveAttribute(
      'href',
      '/administration/users/u1',
    )
    expect(screen.getByText('Accountant')).toBeInTheDocument()
    expect(screen.getByText('Finance Officer')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New user' })).toBeInTheDocument()
  })

  it('searches through the server rather than in the browser', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': VIEWER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /users/?ordering=full_name&page=1': PAGE,
      'GET /users/?ordering=full_name&page=1&q=a': PAGE,
    })
    renderAt('/administration/users')
    await screen.findByRole('table', { name: 'Users' })
    expect(screen.queryByRole('button', { name: 'New user' })).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Search'), 'a')
    await waitFor(() => expect(calls.some((c) => c.path.includes('q=a'))).toBe(true))
  })

  it('shows the temporary password once after creating a user', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': MANAGER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /users/?ordering=full_name&page=1': PAGE,
      'POST /users/': {
        status: 201,
        body: {
          ...row({ id: 'u2', full_name: 'New Person' }),
          temporary_password: 'Tmp-pass-12345',
        },
      },
    })
    renderAt('/administration/users')
    await userEvent.click(await screen.findByRole('button', { name: 'New user' }))
    await userEvent.type(screen.getByLabelText('Full name'), 'New Person')
    await userEvent.type(screen.getByLabelText('Username'), 'new.person')
    await userEvent.type(screen.getByLabelText('Email'), 'n@example.org')
    await userEvent.click(screen.getByRole('button', { name: 'Create user' }))
    expect(await screen.findByText('Tmp-pass-12345')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ username: 'new.person' })
  })

  it('sends a reset link instead of showing any password', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': MANAGER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /users/u1/': { body: row() },
      'GET /rbac/roles/': { body: { results: [] } },
      'POST /users/u1/send-reset-link/': { body: { detail: 'A reset link has been sent.' } },
    })
    renderAt('/administration/users/u1')
    expect(screen.queryByRole('button', { name: /temporary password/i })).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Send a password reset link' }))
    expect(await screen.findByRole('status')).toHaveTextContent(/alice@example.org/)
    expect(calls.some((c) => c.path === '/users/u1/send-reset-link/')).toBe(true)
  })

  it('offers to reset two-factor only when it is on, and shows a refusal', async () => {
    mockApi({
      'GET /auth/me/': MANAGER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /users/u1/': {
        body: row({ two_factor: { enabled: true, required: false, setup_required: false } }),
      },
      'GET /rbac/roles/': { body: { results: [] } },
      'POST /users/u1/reset-two-factor/': apiError(
        403,
        'sensitive_account',
        'This person holds a sensitive role, so this can only be done from the server console.',
      ),
    })
    renderAt('/administration/users/u1')
    await userEvent.click(await screen.findByRole('button', { name: 'Reset two-factor sign-in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/sensitive role/)
  })

  it('points to the Approval Centre for sensitive roles instead of offering them', async () => {
    mockApi({
      'GET /auth/me/': MANAGER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /users/u1/': { body: row({ roles: [] }) },
      'GET /rbac/roles/': {
        body: {
          results: [
            {
              id: 'r1',
              name: 'Storekeeper',
              is_active: true,
              is_sensitive: false,
              sensitive_reasons: [],
            },
            {
              id: 'r2',
              name: 'Administrator',
              is_active: true,
              is_sensitive: true,
              sensitive_reasons: ['x'],
            },
          ],
        },
      },
    })
    renderAt('/administration/users/u1')
    await screen.findByLabelText('Give a role')
    expect(screen.getByRole('option', { name: 'Storekeeper' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Administrator' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Grant a sensitive role' })).toBeInTheDocument()
  })
})

const DASH: DashboardData = {
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
      note: '',
    },
  ],
  approvals: { waiting_for_me: 2, open_in_my_scope: 5, mine_open: 1 },
  finance: null,
  recent_activity: null,
  notifications: { unread: 0, latest: [] },
  department: null,
}

describe('dashboard', () => {
  it('labels reference figures and live counts differently', async () => {
    mockApi({
      'GET /auth/me/': meAs({ approvals: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /dashboard/': { body: DASH },
    })
    renderAt('/')
    expect(await screen.findByText('Reference figure (not yet verified)')).toBeInTheDocument()
    expect(screen.getByText('Live count from records')).toBeInTheDocument()
    expect(screen.getByText(/earlier reference figure was 15/)).toBeInTheDocument()
    expect(screen.getByText('85')).toBeInTheDocument()
    expect(screen.queryByText('Financial summary')).not.toBeInTheDocument()
    expect(screen.queryByText('Recent activity')).not.toBeInTheDocument()
  })

  it('a department dashboard the person cannot reach says so plainly', async () => {
    mockApi({
      'GET /auth/me/': meAs({}),
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /dashboard/departments/d9/': apiError(404, 'not_found', 'Not found.'),
    })
    renderAt('/departments/d9/dashboard')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /not found, or you do not have access/,
    )
  })
})
