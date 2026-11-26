import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { AuthProvider } from '../auth/AuthContext'
import { apiError, meAs, mockApi } from '../../test/mockApi'
import type { RequestDetail } from './types'

const HEALTH = { body: { status: 'ok', database: 'ok' } }
const SUMMARY = { body: { pending: 1, unread_notifications: 2 } }
const APPROVER = meAs({ approvals: { VIEW: 'ASSIGNED', APPROVE: 'ASSIGNED', REJECT: 'ASSIGNED' } })
const REQUESTER = meAs({ approvals: { VIEW: 'OWN', CREATE: 'OWN' } })

const NO_ABILITIES = {
  edit: false,
  submit: false,
  cancel: false,
  review: false,
  approve: false,
  reject: false,
  comment: false,
}

function request(overrides: Partial<RequestDetail> = {}): RequestDetail {
  return {
    id: 'r1',
    request_number: 'TCOS-REQ-2026-000001',
    request_type: 'GENERAL',
    type_label: 'General request',
    title: 'Buy school books',
    status: 'SUBMITTED',
    risk_level: 'LOW',
    amount_tzs: 150000,
    requester: { id: 'u1', name: 'Rita Requester' },
    department: { id: 'd1', name: 'Finance' },
    current_step: 1,
    waiting_for: [{ id: 'u2', name: 'Harry Head' }],
    submitted_at: '2026-11-20T04:00:00Z',
    decided_at: null,
    created_at: '2026-11-20T03:00:00Z',
    can: NO_ABILITIES,
    description: 'Term 1',
    attachments: [],
    can_attach_files: false,
    decision_comment: '',
    payload: { kind: '', kind_label: '' },
    version: 2,
    needs_password: false,
    route: [
      {
        order: 1,
        label: 'Head of the department',
        source: 'CHAIN',
        escalated_to: null,
        state: 'current',
      },
    ],
    history: [
      {
        id: 1,
        action: 'CREATE',
        actor: { id: 'u1', name: 'Rita Requester' },
        from_status: '',
        to_status: 'DRAFT',
        step: 0,
        comment: '',
        at: '2026-11-20T03:00:00Z',
      },
      {
        id: 2,
        action: 'SUBMIT',
        actor: { id: 'u1', name: 'Rita Requester' },
        from_status: 'DRAFT',
        to_status: 'SUBMITTED',
        step: 1,
        comment: '',
        at: '2026-11-20T04:00:00Z',
      },
    ],
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

describe('approval centre', () => {
  it('lists requests, shows the badge and links to the detail', async () => {
    mockApi({
      'GET /auth/me/': APPROVER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /approvals/requests/?view=mine': {
        body: { count: 0, next: null, previous: null, results: [] },
      },
      'GET /approvals/requests/?view=pending': {
        body: { count: 1, next: null, previous: null, results: [request()] },
      },
    })
    renderAt('/approvals?tab=pending')
    const link = await screen.findByRole('link', { name: 'Buy school books' })
    expect(link).toHaveAttribute('href', '/approvals/r1')
    expect(screen.getByText('1 request')).toBeInTheDocument()
    expect(screen.getByLabelText('3 waiting')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'New request' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Grant a sensitive role' })).not.toBeInTheDocument()
  })

  it('the requester sees no approve or reject buttons on their own request', async () => {
    mockApi({
      'GET /auth/me/': REQUESTER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /approvals/requests/r1/': {
        body: request({ can: { ...NO_ABILITIES, cancel: true, comment: true } }),
      },
    })
    renderAt('/approvals/r1')
    expect(await screen.findByRole('heading', { name: 'Buy school books' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel request' })).toBeInTheDocument()
    const history = within(screen.getByRole('list', { name: 'History' }))
    expect(history.getByText('Submitted')).toBeInTheDocument()
  })

  it('an approver can approve, and a high-risk decision asks for the password', async () => {
    const decided = request({ status: 'APPROVED', can: NO_ABILITIES })
    const { calls } = mockApi({
      'GET /auth/me/': APPROVER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /approvals/requests/r1/': {
        body: request({
          risk_level: 'HIGH',
          needs_password: true,
          can: { ...NO_ABILITIES, approve: true, reject: true, review: true },
        }),
      },
      'POST /approvals/requests/r1/approve/': { body: decided },
    })
    renderAt('/approvals/r1')
    await userEvent.type(await screen.findByLabelText(/Your password/), 'secret-password-1')
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument(),
    )
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.body).toEqual({ comment: '', password: 'secret-password-1' })
  })

  it('shows the server refusal in plain words', async () => {
    mockApi({
      'GET /auth/me/': APPROVER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /approvals/requests/r1/': {
        body: request({ can: { ...NO_ABILITIES, approve: true, reject: true } }),
      },
      'POST /approvals/requests/r1/reject/': apiError(400, 'validation_error', 'x', {
        comment: ['Say why you are rejecting this request.'],
      }),
    })
    renderAt('/approvals/r1')
    await userEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Say why you are rejecting')
  })

  it('a new request is saved then submitted, sending content only', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': REQUESTER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'POST /approvals/requests/': { status: 201, body: request({ id: 'r9', status: 'DRAFT' }) },
      'POST /approvals/requests/r9/submit/': { body: request({ id: 'r9' }) },
      'GET /approvals/requests/r9/': { body: request({ id: 'r9' }) },
    })
    renderAt('/approvals/new')
    await userEvent.type(await screen.findByLabelText('Title'), 'Chairs')
    await userEvent.type(screen.getByLabelText(/Amount in TZS/), '2500000')
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }))
    await screen.findByRole('heading', { name: 'Buy school books' })
    const created = calls.find((c) => c.path === '/approvals/requests/')
    expect(created?.body).toEqual({
      title: 'Chairs',
      description: '',
      kind: '',
      amount_tzs: 2500000,
    })
    expect(Object.keys(created?.body as object)).not.toContain('approver')
  })
})

describe('sensitive role grants', () => {
  const ADMIN = meAs({
    approvals: { VIEW: 'ALL' },
    users: { VIEW: 'ALL', MANAGE_USERS: 'ALL' },
    administration: { VIEW: 'ALL' },
  })

  it('offers only sensitive roles and sends the request for approval', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': ADMIN,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /rbac/roles/': {
        body: {
          results: [
            {
              id: 'a',
              name: 'Medical Officer',
              is_active: true,
              is_sensitive: true,
              sensitive_reasons: ['Can see medical records (medical)'],
            },
            {
              id: 'b',
              name: 'Storekeeper',
              is_active: true,
              is_sensitive: false,
              sensitive_reasons: [],
            },
          ],
        },
      },
      'GET /organisation/people/?q=nina': {
        body: {
          count: 1,
          next: null,
          previous: null,
          results: [{ id: 'p1', full_name: 'Nina New', username: 'nina' }],
        },
      },
      'POST /approvals/role-grants/': {
        status: 201,
        body: request({ id: 'g1', title: 'Grant Medical Officer to Nina New' }),
      },
      'GET /approvals/requests/g1/': {
        body: request({ id: 'g1', title: 'Grant Medical Officer to Nina New' }),
      },
    })
    renderAt('/approvals/role-grant')
    const select = await screen.findByLabelText('Role')
    expect(within(select).queryByText('Storekeeper')).not.toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText('Type a name'), 'nina')
    await userEvent.click(screen.getByRole('button', { name: 'Find person' }))
    await userEvent.selectOptions(await screen.findByLabelText('Person results'), 'p1')
    await userEvent.selectOptions(select, 'a')
    expect(screen.getByText('Can see medical records (medical)')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Why does this person/), 'Joins the clinic')
    await userEvent.click(screen.getByRole('button', { name: 'Send for approval' }))
    await screen.findByRole('heading', { name: /Grant Medical Officer/ })
    const sent = calls.find((c) => c.path === '/approvals/role-grants/')
    expect(sent?.body).toEqual({
      user: 'p1',
      role: 'a',
      reason: 'Joins the clinic',
      valid_to: null,
    })
  })

  it('is hidden from people who cannot manage users', async () => {
    mockApi({
      'GET /auth/me/': REQUESTER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
    })
    renderAt('/approvals/role-grant')
    expect(
      await screen.findByRole('heading', { name: /not allowed|permission|access/i }),
    ).toBeInTheDocument()
  })
})

describe('TZS limits and access review', () => {
  const POLICY = {
    id: 'p1',
    version_number: 1,
    state: 'ACTIVE',
    state_label: 'In force',
    low_max: 200000,
    medium_max: 2000000,
    always_high: ['PAYROLL'],
    reason: 'Provisional',
    is_ratified: false,
    ratified_by: null,
    ratified_at: null,
    request_id: null,
    created_at: '2026-11-20T00:00:00Z',
  }

  it('shows the limits, says they are provisional, and proposes a change for approval', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': meAs({
        approvals: { VIEW: 'ALL' },
        administration: { VIEW: 'ALL', EDIT: 'ALL' },
      }),
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /approvals/tzs-limits/': {
        body: {
          active: POLICY,
          pending: null,
          history: [POLICY],
          kinds: [{ code: 'PAYROLL', label: 'Payroll' }],
          explanation: 'Risk level is set by the server.',
          can_propose: true,
        },
      },
      'POST /approvals/tzs-limits/propose/': {
        status: 201,
        body: request({ id: 'l1', title: 'TZS limits, version 2' }),
      },
      'GET /approvals/requests/l1/': {
        body: request({ id: 'l1', title: 'TZS limits, version 2' }),
      },
    })
    renderAt('/approvals/limits')
    expect(await screen.findByText(/Provisional: not yet ratified/)).toBeInTheDocument()
    expect(screen.getByText('Low risk: up to TZS 200,000')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Reason'), 'Board guidance')
    await userEvent.click(screen.getByRole('button', { name: 'Send for approval' }))
    await screen.findByRole('heading', { name: 'TZS limits, version 2' })
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      low_max: 200000,
      medium_max: 2000000,
      always_high: ['PAYROLL'],
      reason: 'Board guidance',
    })
  })

  it('hides the proposal form from people who cannot propose', async () => {
    mockApi({
      'GET /auth/me/': REQUESTER,
      'GET /health/': HEALTH,
      'GET /approvals/summary/': SUMMARY,
      'GET /approvals/tzs-limits/': {
        body: {
          active: POLICY,
          pending: null,
          history: [POLICY],
          kinds: [],
          explanation: 'x',
          can_propose: false,
        },
      },
    })
    renderAt('/approvals/limits')
    await screen.findByText(/Provisional: not yet/)
    expect(screen.queryByRole('form', { name: 'Propose new limits' })).not.toBeInTheDocument()
  })

  it('access review shows who can see which data and where it is kept', async () => {
    mockApi({
      'GET /auth/me/': meAs({ audit: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
      'GET /rbac/access-review/': {
        body: {
          generated_at: '2026-11-20T04:00:00Z',
          hosting: {
            region: null,
            note: 'Not set. The hosting region is still an open decision for the owner.',
          },
          classes: [
            {
              code: 'medical',
              label: 'Medical records',
              classification: 'CHILD_SENSITIVE',
              stored: 'Central PostgreSQL database only. Never copied to phones or computers.',
              people: [
                {
                  id: 'u1',
                  name: 'Mona Medic',
                  username: 'mona',
                  scope: 'ALL',
                  roles: ['Medical Officer'],
                },
              ],
            },
          ],
          sensitive_roles: [
            { id: 'r1', name: 'Medical Officer', reasons: [], holders: ['Mona Medic'] },
          ],
          outside_the_application: ['The server operator can reach the database files.'],
        },
      },
    })
    renderAt('/administration/access-review')
    expect(await screen.findByText(/Mona Medic \(mona\)/)).toBeInTheDocument()
    expect(screen.getByText('Not set')).toBeInTheDocument()
    expect(screen.getByText(/Never copied to phones/)).toBeInTheDocument()
  })
})
