import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { AuthProvider } from '../auth/AuthContext'
import { FULL_ACCESS, apiError, meAs, mockApi } from '../../test/mockApi'
import { activeFilters, describeChange, humanise } from './types'

const ROW = {
  id: 7,
  occurred_at: '2026-11-20T04:12:00Z',
  actor_id: null,
  actor_username: 'alice',
  event_type: 'ROLE_CREATED',
  object_type: 'rbac.Role',
  object_id: 'r1',
  success: true,
  ip_address: '10.0.0.5',
  request_id: 'req-12345678',
}
const FAILED = { ...ROW, id: 6, actor_username: 'bob', event_type: 'LOGIN_FAILED', success: false }
const PAGE = { count: 2, next: null, previous: null, results: [ROW, FAILED] }
const TYPES = { results: ['LOGIN_FAILED', 'ROLE_CREATED'] }
const HEALTH = { body: { status: 'ok', database: 'ok' } }

function renderAudit() {
  return render(
    <MemoryRouter initialEntries={['/administration/audit']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('audit log screen', () => {
  it('lists events with a human reading of each one', async () => {
    mockApi({
      'GET /auth/me/': meAs({ ...FULL_ACCESS, audit: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /audit/event-types/': { body: TYPES },
      'GET /audit/events/': { body: PAGE },
    })
    renderAudit()

    const table = within(await screen.findByRole('table'))
    expect(table.getByText('Role created')).toBeInTheDocument()
    expect(table.getByText('Login failed')).toBeInTheDocument()
    expect(screen.getByText('2 events')).toBeInTheDocument()
    expect(table.getByText('Failed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Export CSV/ })).not.toBeInTheDocument()
  })

  it('is refused for people without audit access, and the API is never asked', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': meAs({ finance: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
    })
    renderAudit()
    expect(await screen.findByText(/not allowed|permission/i)).toBeInTheDocument()
    expect(calls.some((call) => call.path.startsWith('/audit'))).toBe(false)
  })

  it('applies the filters that were filled in and nothing else', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': meAs({ audit: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /audit/event-types/': { body: TYPES },
      'GET /audit/events/': { body: PAGE },
      'GET /audit/events/?q=bob&event_type=LOGIN_FAILED&success=false': {
        body: { ...PAGE, count: 1, results: [FAILED] },
      },
    })
    const user = userEvent.setup()
    renderAudit()
    await screen.findByRole('table')

    await user.type(screen.getByLabelText('Search'), 'bob')
    await user.selectOptions(screen.getByLabelText('Event type'), 'LOGIN_FAILED')
    await user.selectOptions(screen.getByLabelText('Outcome'), 'false')
    await user.click(screen.getByRole('button', { name: 'Apply filters' }))

    expect(await screen.findByText('1 event')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).queryByText('Role created')).toBeNull()
    const last = calls.filter((call) => call.path.startsWith('/audit/events/')).at(-1)
    expect(last?.path).toBe('/audit/events/?q=bob&event_type=LOGIN_FAILED&success=false')
  })

  it('shows what changed when a row is opened', async () => {
    mockApi({
      'GET /auth/me/': meAs({ audit: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /audit/event-types/': { body: TYPES },
      'GET /audit/events/': { body: PAGE },
      'GET /audit/events/7/': {
        body: {
          ...ROW,
          user_agent: 'Safari on iPhone',
          changes: { name: { from: 'Old', to: 'New' }, is_active: { from: null, to: true } },
          metadata: {},
          department_id: null,
          prev_hash: 'a'.repeat(64),
          event_hash: 'b'.repeat(64),
        },
      },
    })
    const user = userEvent.setup()
    renderAudit()
    await screen.findByRole('table')

    await user.click(screen.getByRole('button', { name: 'Show details of event 7' }))

    const panel = await screen.findByText('What changed')
    const list = within(panel.parentElement as HTMLElement)
    expect(list.getByText(/Old → New/)).toBeInTheDocument()
    expect(list.getByText(/— → true/)).toBeInTheDocument()
    expect(list.getByText('Safari on iPhone')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide details of event 7' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('pages through older events', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': meAs({ audit: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /audit/event-types/': { body: TYPES },
      'GET /audit/events/': { body: { ...PAGE, next: 'x', count: 30 } },
      'GET /audit/events/?page=2': {
        body: { count: 30, next: null, previous: 'x', results: [FAILED] },
      },
    })
    const user = userEvent.setup()
    renderAudit()
    await screen.findByRole('table')
    expect(screen.getByRole('button', { name: 'Newer' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Older' }))

    expect(await screen.findByText('Page 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Older' })).toBeDisabled()
    expect(calls.at(-1)?.path).toBe('/audit/events/?page=2')
  })

  it('shows an empty state and an error state', async () => {
    mockApi({
      'GET /auth/me/': meAs({ audit: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /audit/event-types/': { body: TYPES },
      'GET /audit/events/': { body: { count: 0, next: null, previous: null, results: [] } },
      'GET /audit/events/?date_from=bad': apiError(400, 'validation_error', 'Invalid.', {
        date_from: ['Enter a valid date.'],
      }),
    })
    const user = userEvent.setup()
    renderAudit()
    expect(await screen.findByText('No events match these filters.')).toBeInTheDocument()

    // A date typed in a browser that does not support date pickers can reach the server wrongly.
    await user.type(screen.getByLabelText('From date'), '2026-01-01')
    await user.click(screen.getByRole('button', { name: 'Apply filters' }))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('exports only for people with export permission, and says it was recorded', async () => {
    const createUrl = vi.fn(() => 'blob:test')
    URL.createObjectURL = createUrl
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { calls } = mockApi({
      'GET /auth/me/': meAs({ audit: { VIEW: 'ALL', EXPORT: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /audit/event-types/': { body: TYPES },
      'GET /audit/events/': { body: PAGE },
      'POST /audit/export/': { body: { ok: true } },
    })
    const user = userEvent.setup()
    renderAudit()
    await screen.findByRole('table')

    await user.click(screen.getByRole('button', { name: 'Export CSV' }))

    expect(await screen.findByText(/recorded in the audit log/)).toBeInTheDocument()
    expect(createUrl).toHaveBeenCalled()
    const post = calls.find((call) => call.method === 'POST')
    expect(post?.headers.get('X-CSRFToken')).toBe('test-token')
    expect(post?.body).toEqual({})
  })

  it('shows the server reason when an export is too large', async () => {
    mockApi({
      'GET /auth/me/': meAs({ audit: { VIEW: 'ALL', EXPORT: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /audit/event-types/': { body: TYPES },
      'GET /audit/events/': { body: PAGE },
      'POST /audit/export/': apiError(400, 'validation_error', 'Invalid.', {
        detail: ['60000 events match. Narrow the filters to 50000 or fewer.'],
      }),
    })
    const user = userEvent.setup()
    renderAudit()
    await screen.findByRole('table')
    await user.click(screen.getByRole('button', { name: 'Export CSV' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Narrow the filters')
  })
})

describe('audit helpers', () => {
  it('humanises event codes', () => {
    expect(humanise('PERMISSION_CHANGED')).toBe('Permission changed')
  })

  it('keeps only filled-in filters', () => {
    expect(
      activeFilters({
        q: ' ',
        event_type: 'LOGIN_FAILED',
        success: '',
        date_from: '',
        date_to: '',
        object_type: '',
      }),
    ).toEqual({ event_type: 'LOGIN_FAILED' })
  })

  it('describes changes of every shape', () => {
    expect(describeChange({ from: 'a', to: 'b' })).toBe('a → b')
    expect(describeChange({ from: null, to: 3 })).toBe('— → 3')
    expect(describeChange(['x', 'y'])).toBe('["x","y"]')
    expect(describeChange(5)).toBe('5')
  })
})
