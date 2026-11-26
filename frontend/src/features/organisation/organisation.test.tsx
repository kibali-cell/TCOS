import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { AuthProvider } from '../auth/AuthContext'
import { FULL_ACCESS, apiError, meAs, mockApi } from '../../test/mockApi'
import type { Assignment, Department, Position } from './types'

const FULL = {
  ...FULL_ACCESS,
  administration: { VIEW: 'ALL', CREATE: 'ALL', EDIT: 'ALL', DELETE: 'ALL' },
}
const HEALTH = { body: { status: 'ok', database: 'ok' } }
const page = <T,>(results: T[]) => ({
  body: { count: results.length, next: null, previous: null, results },
})

const ALPHA: Department = {
  id: 'd1',
  code: 'ALPHA',
  name: 'Alpha',
  description: 'First',
  parent: null,
  head: null,
  is_active: true,
  is_archived: false,
  version: 1,
  staff_count: 1,
  position_count: 1,
}
const BETA: Department = {
  ...ALPHA,
  id: 'd2',
  code: 'BETA',
  name: 'Beta',
  parent: { id: 'd1', name: 'Alpha' },
  staff_count: 0,
  position_count: 0,
}
const CLERK: Position = {
  id: 'p1',
  title: 'Clerk',
  department: { id: 'd1', name: 'Alpha' },
  reports_to: null,
  is_department_head_position: false,
  is_active: true,
  is_archived: false,
  version: 1,
  holder_count: 1,
}
const WORKER: Assignment = {
  id: 'a1',
  user: { id: 'u1', full_name: 'Worker One', username: 'worker' },
  position: { id: 'p1', title: 'Clerk' },
  department: { id: 'd1', name: 'Alpha' },
  is_primary: true,
  reports_to_user: null,
  start_date: '2026-11-01',
  end_date: null,
  is_current: true,
}

const TREE = {
  results: [
    {
      id: 'd1',
      code: 'ALPHA',
      name: 'Alpha',
      description: '',
      head: { id: 'u1', full_name: 'Worker One' },
      is_archived: false,
      staff_count: 1,
      positions: [
        {
          id: 'p1',
          title: 'Clerk',
          reports_to_id: null,
          is_department_head_position: true,
          holders: [
            { assignment_id: 'a1', user_id: 'u1', full_name: 'Worker One', is_primary: true },
          ],
        },
        {
          id: 'p2',
          title: 'Assistant',
          reports_to_id: 'p1',
          is_department_head_position: false,
          holders: [],
        },
      ],
      children: [
        {
          id: 'd2',
          code: 'BETA',
          name: 'Beta',
          description: '',
          head: null,
          is_archived: false,
          staff_count: 0,
          positions: [],
          children: [],
        },
      ],
    },
  ],
}

const DEPT_LIST = '/organisation/departments/?archived=all&page_size=100'
const DEPT_OPEN = '/organisation/departments/?archived=false&page_size=100'
const POS_ALL = '/organisation/positions/?archived=all&page_size=100'
const POS_OPEN = '/organisation/positions/?archived=false&page_size=100'

function renderOrg() {
  return render(
    <MemoryRouter initialEntries={['/administration/organisation']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function openTab(name: string) {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name }))
  return user
}

afterEach(() => vi.restoreAllMocks())

describe('organisation: access', () => {
  it('is refused without administration access and the API is never asked', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': meAs({ finance: { VIEW: 'ALL' } }),
      'GET /health/': HEALTH,
    })
    renderOrg()
    expect(await screen.findByText(/not allowed|permission/i)).toBeInTheDocument()
    expect(calls.some((call) => call.path.startsWith('/organisation'))).toBe(false)
  })
})

describe('organisation: chart', () => {
  it('shows departments nested, with head, people, positions and who holds them', async () => {
    mockApi({
      'GET /auth/me/': meAs(FULL),
      'GET /health/': HEALTH,
      'GET /organisation/tree/': { body: TREE },
    })
    renderOrg()

    const chart = within(await screen.findByRole('region', { name: 'Organisation chart' }))
    expect(await chart.findByText('Alpha')).toBeInTheDocument()
    expect(chart.getByText(/Head: Worker One · 1 person/)).toBeInTheDocument()
    expect(chart.getByText('Beta')).toBeInTheDocument()
    expect(chart.getByText('Head post')).toBeInTheDocument()
    expect(chart.getByText(/reports to Clerk/)).toBeInTheDocument()
    expect(chart.getByText('Vacant')).toBeInTheDocument()
    expect(chart.getAllByText('Worker One').length).toBeGreaterThan(0)
  })

  it('asks for archived departments only when told to', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': meAs(FULL),
      'GET /health/': HEALTH,
      'GET /organisation/tree/': { body: TREE },
      'GET /organisation/tree/?include_archived=true': { body: TREE },
    })
    const user = userEvent.setup()
    renderOrg()
    await screen.findByRole('region', { name: 'Organisation chart' })
    await user.click(screen.getByLabelText('Show archived departments'))
    await waitFor(() =>
      expect(calls.at(-1)?.path).toBe('/organisation/tree/?include_archived=true'),
    )
  })

  it('shows an error if the chart cannot load', async () => {
    mockApi({
      'GET /auth/me/': meAs(FULL),
      'GET /health/': HEALTH,
      'GET /organisation/tree/': apiError(500, 'server_error', 'The server had a problem.'),
    })
    renderOrg()
    expect(await screen.findByRole('alert')).toHaveTextContent('The server had a problem.')
  })
})

describe('organisation: departments', () => {
  const base = {
    'GET /auth/me/': meAs(FULL),
    'GET /health/': HEALTH,
    'GET /organisation/tree/': { body: TREE },
    [`GET ${DEPT_LIST}`]: page([ALPHA, BETA]),
  }

  it('explains what blocks archiving and disables the button', async () => {
    mockApi({
      ...base,
      'GET /organisation/departments/d1/': {
        body: { ...ALPHA, archive_blockers: ['1 person still works in it (move them first)'] },
      },
      'GET /organisation/assignments/?department=d1&page_size=100': page([WORKER]),
    })
    const user = await (async () => {
      renderOrg()
      return openTab('Departments')
    })()
    await user.click(await screen.findByRole('button', { name: /^Alpha/ }))

    expect(await screen.findByText(/1 person still works in it/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Archive department' })).toBeDisabled()
  })

  it('archives a free department after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi({
      ...base,
      'GET /organisation/departments/d2/': { body: { ...BETA, archive_blockers: [] } },
      'GET /organisation/assignments/?department=d2&page_size=100': page([]),
      'POST /organisation/departments/d2/archive/': { body: { ...BETA, is_archived: true } },
    })
    renderOrg()
    const user = await openTab('Departments')
    await user.click(await screen.findByRole('button', { name: /Beta/ }))
    await user.click(await screen.findByRole('button', { name: 'Archive department' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Department archived.')
    expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/d2/archive/'))).toBe(true)
  })

  it('creates a department and reports a server refusal in plain words', async () => {
    const { calls } = mockApi({
      ...base,
      'POST /organisation/departments/': (request: { body: unknown }) => {
        const body = request.body as { code: string }
        return body.code === 'TAKEN'
          ? apiError(400, 'validation_error', 'Invalid.', {
              code: ['Another department already has this code.'],
            })
          : { status: 201, body: { ...ALPHA, id: 'd9', name: 'Laundry' } }
      },
    })
    renderOrg()
    const user = await openTab('Departments')
    const form = within(await screen.findByRole('form', { name: 'New department' }))

    await user.type(form.getByLabelText('Code'), 'TAKEN')
    await user.type(form.getByLabelText('Name'), 'Laundry')
    await user.click(form.getByRole('button', { name: 'Create department' }))
    expect(await form.findByRole('alert')).toHaveTextContent('already has this code')

    await user.clear(form.getByLabelText('Code'))
    await user.type(form.getByLabelText('Code'), 'LAUNDRY')
    await user.selectOptions(form.getByLabelText('Sits under'), 'd1')
    await user.click(form.getByRole('button', { name: 'Create department' }))
    expect(await form.findByRole('status')).toHaveTextContent('Department "Laundry" created.')
    const last = calls.filter((c) => c.method === 'POST').at(-1)
    expect(last?.body).toEqual({
      code: 'LAUNDRY',
      name: 'Laundry',
      description: '',
      parent: 'd1',
    })
  })

  it('saves edits and names a head from the people who work there', async () => {
    const { calls } = mockApi({
      ...base,
      'GET /organisation/departments/d1/': { body: { ...ALPHA, archive_blockers: [] } },
      'GET /organisation/assignments/?department=d1&page_size=100': page([WORKER]),
      'PATCH /organisation/departments/d1/': { body: ALPHA },
      'PUT /organisation/departments/d1/head/': { body: ALPHA },
    })
    renderOrg()
    const user = await openTab('Departments')
    await user.click(await screen.findByRole('button', { name: /^Alpha/ }))
    const editor = within(await screen.findByRole('region', { name: 'Department Alpha' }))

    await user.clear(editor.getByLabelText('Name'))
    await user.type(editor.getByLabelText('Name'), 'Alpha Renamed')
    await user.click(editor.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      name: 'Alpha Renamed',
      description: 'First',
      parent: null,
    })

    await user.selectOptions(editor.getByLabelText('Department head'), 'u1')
    await user.click(editor.getByRole('button', { name: 'Save head' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ user: 'u1' })
  })

  it('a view-only person sees no create, save or archive controls', async () => {
    mockApi({
      ...base,
      'GET /auth/me/': meAs({ administration: { VIEW: 'ALL' } }),
      'GET /organisation/departments/d1/': { body: { ...ALPHA, archive_blockers: [] } },
      'GET /organisation/assignments/?department=d1&page_size=100': page([WORKER]),
    })
    renderOrg()
    const user = await openTab('Departments')
    await user.click(await screen.findByRole('button', { name: /^Alpha/ }))
    await screen.findByRole('region', { name: 'Department Alpha' })

    expect(screen.queryByRole('form', { name: 'New department' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Archive department' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toBeDisabled()
  })
})

describe('organisation: positions', () => {
  const base = {
    'GET /auth/me/': meAs(FULL),
    'GET /health/': HEALTH,
    'GET /organisation/tree/': { body: TREE },
    [`GET ${POS_ALL}`]: page([CLERK]),
    [`GET ${DEPT_OPEN}`]: page([ALPHA, BETA]),
  }

  it('creates a position that reports to another', async () => {
    const { calls } = mockApi({
      ...base,
      'POST /organisation/positions/': { status: 201, body: CLERK },
    })
    renderOrg()
    const user = await openTab('Positions')
    const form = within(await screen.findByRole('form', { name: 'New position' }))
    await user.selectOptions(form.getByLabelText('Department'), 'd2')
    await user.type(form.getByLabelText('Title'), 'Supervisor')
    await user.selectOptions(form.getByLabelText('Reports to'), 'p1')
    await user.click(form.getByLabelText('This is the department head post'))
    await user.click(form.getByRole('button', { name: 'Create position' }))

    expect(await form.findByRole('status')).toHaveTextContent('Position "Supervisor" created.')
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      department: 'd2',
      title: 'Supervisor',
      reports_to: 'p1',
      is_department_head_position: true,
    })
  })

  it('filters by department and shows why a position cannot be archived', async () => {
    mockApi({
      ...base,
      'GET /organisation/positions/p1/': {
        body: { ...CLERK, archive_blockers: ['1 person currently holds it (end first)'] },
      },
    })
    renderOrg()
    const user = await openTab('Positions')
    await screen.findByRole('button', { name: /Clerk/ })
    await user.selectOptions(screen.getByLabelText('Show positions in'), 'd2')
    expect(screen.getByText('No positions here yet.')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Show positions in'), '')
    await user.click(screen.getByRole('button', { name: /Clerk/ }))

    expect(await screen.findByText(/1 person currently holds it/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Archive position' })).toBeDisabled()
  })

  it('shows a cycle refusal from the server', async () => {
    mockApi({
      ...base,
      'GET /organisation/positions/p1/': { body: { ...CLERK, archive_blockers: [] } },
      'PATCH /organisation/positions/p1/': apiError(400, 'validation_error', 'Invalid.', {
        reports_to: ['A position cannot report to itself or to one that reports to it.'],
      }),
    })
    renderOrg()
    const user = await openTab('Positions')
    await user.click(await screen.findByRole('button', { name: /Clerk/ }))
    const editor = within(await screen.findByRole('region', { name: 'Position Clerk' }))
    await user.click(editor.getByRole('button', { name: 'Save changes' }))
    expect(await editor.findByRole('alert')).toHaveTextContent('cannot report to itself')
  })
})

describe('organisation: staff', () => {
  const base = {
    'GET /auth/me/': meAs(FULL),
    'GET /health/': HEALTH,
    'GET /organisation/tree/': { body: TREE },
    'GET /organisation/assignments/': page([WORKER]),
    [`GET ${POS_OPEN}`]: page([CLERK, { ...CLERK, id: 'p2', title: 'Auditor' }]),
  }

  it('lists current assignments and searches by name', async () => {
    const { calls } = mockApi({
      ...base,
      'GET /organisation/assignments/?q=nobody': page([]),
    })
    renderOrg()
    const user = await openTab('Staff')
    expect(await screen.findByText(/Clerk, Alpha · main/)).toBeInTheDocument()

    await user.type(screen.getByRole('textbox', { name: 'Search staff' }), 'nobody')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText('Nobody is assigned yet.')).toBeInTheDocument()
    expect(calls.at(-1)?.path).toBe('/organisation/assignments/?q=nobody')
  })

  it('assigns a person found by name to a position', async () => {
    const { calls } = mockApi({
      ...base,
      'GET /organisation/people/?q=ann': page([
        { id: 'u7', full_name: 'Ann Moshi', username: 'ann' },
      ]),
      'POST /organisation/assignments/': { status: 201, body: WORKER },
    })
    renderOrg()
    const user = await openTab('Staff')
    const form = within(await screen.findByRole('form', { name: 'Assign a person' }))
    expect(form.getByRole('button', { name: 'Assign' })).toBeDisabled()

    await user.type(form.getByLabelText('Person'), 'ann')
    await user.click(form.getByRole('button', { name: 'Find person' }))
    await user.selectOptions(await form.findByLabelText('Person results'), 'u7')
    expect(form.getByText('Ann Moshi')).toBeInTheDocument()
    await user.selectOptions(form.getByLabelText('Position'), 'p2')
    await user.click(form.getByRole('button', { name: 'Assign' }))

    expect(await form.findByRole('status')).toHaveTextContent('Ann Moshi assigned.')
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ user: 'u7', position: 'p2' })
  })

  it('transfers and ends an assignment, and says plainly when the server refuses', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi({
      ...base,
      'POST /organisation/assignments/a1/transfer/': { status: 201, body: WORKER },
      'POST /organisation/assignments/a1/end/': apiError(400, 'validation_error', 'Invalid.', {
        detail: ['This assignment has already ended.'],
      }),
    })
    renderOrg()
    const user = await openTab('Staff')
    await user.click(await screen.findByRole('button', { name: /Worker One/ }))
    const actions = within(await screen.findByRole('group', { name: 'Actions for Worker One' }))

    await user.selectOptions(actions.getByLabelText('Move to another position'), 'p2')
    await user.click(actions.getByRole('button', { name: 'Transfer' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/transfer/'))).toBe(true))
    expect(calls.find((c) => c.path.endsWith('/transfer/'))?.body).toEqual({ position: 'p2' })

    await user.click(await screen.findByRole('button', { name: /Worker One/ }))
    const again = within(await screen.findByRole('group', { name: 'Actions for Worker One' }))
    await user.click(again.getByRole('button', { name: 'End assignment' }))
    expect(await again.findByRole('alert')).toHaveTextContent('already ended')
  })

  it('does not end an assignment if the person cancels', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { calls } = mockApi(base)
    renderOrg()
    const user = await openTab('Staff')
    await user.click(await screen.findByRole('button', { name: /Worker One/ }))
    await user.click(await screen.findByRole('button', { name: 'End assignment' }))
    expect(calls.some((c) => c.path.endsWith('/end/'))).toBe(false)
  })

  it('a view-only person can look but not change', async () => {
    mockApi({ ...base, 'GET /auth/me/': meAs({ administration: { VIEW: 'ALL' } }) })
    renderOrg()
    const user = await openTab('Staff')
    await user.click(await screen.findByRole('button', { name: /Worker One/ }))
    expect(await screen.findByText(/look at assignments but not change/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'End assignment' })).not.toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Assign a person' })).not.toBeInTheDocument()
  })
})

describe('organisation: approval chains', () => {
  const OPTIONS = {
    roles: [{ id: 'r1', name: 'Finance Officer' }],
    approver_types: [
      { value: 'POSITION', label: 'A position' },
      { value: 'ROLE', label: 'A role' },
      { value: 'DEPARTMENT_HEAD', label: 'The department head' },
      { value: 'REPORTS_TO', label: "The requester's line manager" },
      { value: 'USER', label: 'A named person' },
    ],
    default_request_type: 'DEFAULT',
    max_chain_steps: 2,
  }
  const base = {
    'GET /auth/me/': meAs(FULL),
    'GET /health/': HEALTH,
    'GET /organisation/tree/': { body: TREE },
    'GET /organisation/options/': { body: OPTIONS },
    [`GET ${DEPT_OPEN}`]: page([ALPHA, BETA]),
    [`GET ${POS_OPEN}`]: page([CLERK]),
    'GET /organisation/departments/d1/approval-chains/': {
      body: {
        chains: {
          DEFAULT: [
            {
              step_order: 1,
              approver_type: 'DEPARTMENT_HEAD',
              label: 'The department head',
              position: null,
              role: null,
              user: null,
            },
          ],
        },
      },
    },
  }

  it('loads a chain, edits it, and saves the steps in order', async () => {
    const { calls } = mockApi({
      ...base,
      'PUT /organisation/departments/d1/approval-chains/DEFAULT/': {
        body: { request_type: 'DEFAULT', steps: [] },
      },
    })
    renderOrg()
    const user = await openTab('Approval chains')
    await user.selectOptions(await screen.findByLabelText('Department'), 'd1')
    expect(await screen.findByLabelText('Step 1 approver')).toHaveValue('DEPARTMENT_HEAD')

    await user.click(screen.getByRole('button', { name: 'Add a step' }))
    const second = await screen.findByLabelText('Step 2 approver')
    await user.selectOptions(second, 'ROLE')
    const save = screen.getByRole('button', { name: 'Save chain' })
    expect(save).toBeDisabled() // a role step with no role chosen is incomplete
    await user.selectOptions(screen.getByLabelText('Role'), 'r1')
    expect(save).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Move step 2 up' }))
    await user.click(save)

    expect(await screen.findByRole('status')).toHaveTextContent('Chain saved.')
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
      steps: [{ approver_type: 'ROLE', role: 'r1' }, { approver_type: 'DEPARTMENT_HEAD' }],
    })
  })

  it('stops adding steps at the limit and can remove them all', async () => {
    const { calls } = mockApi({
      ...base,
      'PUT /organisation/departments/d1/approval-chains/DEFAULT/': {
        body: { request_type: 'DEFAULT', steps: [] },
      },
    })
    renderOrg()
    const user = await openTab('Approval chains')
    await user.selectOptions(await screen.findByLabelText('Department'), 'd1')
    await screen.findByLabelText('Step 1 approver')
    await user.click(screen.getByRole('button', { name: 'Add a step' }))
    expect(screen.getByRole('button', { name: 'Add a step' })).toBeDisabled() // max is 2

    await user.click(screen.getByRole('button', { name: 'Remove step 2' }))
    await user.click(screen.getByRole('button', { name: 'Remove step 1' }))
    expect(screen.getByText('No approval chain for DEFAULT.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save chain' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Chain removed.')
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ steps: [] })
  })

  it('switches to another kind of request', async () => {
    mockApi(base)
    renderOrg()
    const user = await openTab('Approval chains')
    await user.selectOptions(await screen.findByLabelText('Department'), 'd1')
    await screen.findByLabelText('Step 1 approver')
    await user.clear(screen.getByLabelText('Kind of request'))
    await user.type(screen.getByLabelText('Kind of request'), 'leave')
    expect(screen.getByText('No approval chain for LEAVE.')).toBeInTheDocument()
  })

  it('shows the server reason when a chain is refused', async () => {
    mockApi({
      ...base,
      'PUT /organisation/departments/d1/approval-chains/DEFAULT/': apiError(
        400,
        'validation_error',
        'Invalid.',
        { steps: ['The same approver cannot appear twice in one chain.'] },
      ),
    })
    renderOrg()
    const user = await openTab('Approval chains')
    await user.selectOptions(await screen.findByLabelText('Department'), 'd1')
    await screen.findByLabelText('Step 1 approver')
    await user.click(screen.getByRole('button', { name: 'Save chain' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('cannot appear twice')
  })
})
