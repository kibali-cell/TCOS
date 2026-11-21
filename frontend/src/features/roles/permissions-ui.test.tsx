import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../app/App'
import { AuthProvider } from '../auth/AuthContext'
import { ME, apiError, meAs, mockApi } from '../../test/mockApi'

const CATALOGUE = {
  modules: [
    { code: 'finance', name: 'Financial Management' },
    { code: 'medical', name: 'Medical Management' },
  ],
  actions: ['VIEW', 'CREATE', 'EDIT', 'DELETE', 'APPROVE', 'REJECT', 'EXPORT', 'MANAGE_USERS'],
  scopes: ['ALL', 'DEPARTMENT', 'OWN', 'ASSIGNED'],
}

const STOREKEEPER = {
  id: 'r1111111-1111-4111-8111-111111111111',
  code: 'STOREKEEPER',
  name: 'Storekeeper',
  description: 'Stores and inventory.',
  is_system: true,
  is_active: true,
}
const CUSTOM = {
  id: 'r2222222-2222-4222-8222-222222222222',
  code: 'FIELD_VISITOR',
  name: 'Field Visitor',
  description: '',
  is_system: false,
  is_active: true,
}
const ADMIN_ROLE = {
  id: 'r3333333-3333-4333-8333-333333333333',
  code: 'ADMINISTRATOR',
  name: 'Administrator',
  description: '',
  is_system: true,
  is_active: true,
}

const detail = (role: typeof STOREKEEPER, grants: object[] = []) => ({ ...role, grants })

function renderAt(path: string) {
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

describe('navigation follows permissions', () => {
  it('shows only the modules the person may view', async () => {
    mockApi({
      'GET /auth/me/': meAs({ finance: { VIEW: 'ALL' }, stores: { VIEW: 'DEPARTMENT' } }),
      'GET /health/': HEALTH,
    })
    renderAt('/')

    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    const names = within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent)
    expect(names).toEqual(['Dashboard', 'Financial Management', 'Stores and Inventory'])
  })

  it('hides the roles screen from people without users.VIEW', async () => {
    mockApi({ 'GET /auth/me/': meAs({ finance: { VIEW: 'ALL' } }), 'GET /health/': HEALTH })
    renderAt('/')

    await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(screen.queryByRole('link', { name: 'Roles and permissions' })).not.toBeInTheDocument()
  })

  it('a person with no roles sees only the dashboard', async () => {
    mockApi({ 'GET /auth/me/': meAs({}, []), 'GET /health/': HEALTH })
    renderAt('/')

    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(within(nav).getAllByRole('link')).toHaveLength(1)
  })

  it('typing the address of a module they cannot view shows a refusal, not the module', async () => {
    mockApi({ 'GET /auth/me/': meAs({ finance: { VIEW: 'ALL' } }) })
    renderAt('/modules/medical')

    expect(await screen.findByRole('heading', { name: 'No access' })).toBeInTheDocument()
    expect(screen.queryByText(/not been built yet/i)).not.toBeInTheDocument()
  })

  it('typing the roles address without permission shows a refusal and loads nothing', async () => {
    const { calls } = mockApi({ 'GET /auth/me/': meAs({ finance: { VIEW: 'ALL' } }) })
    renderAt('/administration/roles')

    expect(await screen.findByRole('heading', { name: 'No access' })).toBeInTheDocument()
    expect(calls.some((call) => call.path.startsWith('/rbac'))).toBe(false)
  })

  it('shows the person their roles on the account page', async () => {
    mockApi({
      'GET /auth/me/': meAs({}, [
        { code: 'FINANCE_OFFICER', name: 'Finance Officer', department: null },
        { code: 'PROJECT_MANAGER', name: 'Project Manager', department: 'Department A' },
      ]),
      'GET /auth/sessions/': { body: { results: [] } },
    })
    renderAt('/account')

    expect(
      await screen.findByText('Finance Officer, Project Manager (Department A)'),
    ).toBeInTheDocument()
  })
})

describe('roles and permissions screen', () => {
  function routes(extra: Record<string, never | object> = {}) {
    return {
      'GET /auth/me/': ME,
      'GET /rbac/catalogue/': { body: CATALOGUE },
      'GET /rbac/roles/': {
        body: {
          results: [
            { ...ADMIN_ROLE, holders: 1 },
            { ...STOREKEEPER, holders: 2 },
            { ...CUSTOM, holders: 0 },
          ],
        },
      },
      [`GET /rbac/roles/${STOREKEEPER.id}/`]: {
        body: detail(STOREKEEPER, [{ module: 'finance', action: 'VIEW', scope: 'ALL' }]),
      },
      ...extra,
    }
  }

  it('lists roles with how many people hold each', async () => {
    mockApi(routes())
    renderAt('/administration/roles')

    const list = await screen.findByRole('list', { name: 'Roles' })
    expect(within(list).getByRole('button', { name: /Storekeeper 2 people/ })).toBeInTheDocument()
    expect(within(list).getByRole('button', { name: /Administrator 1 person/ })).toBeInTheDocument()
  })

  it('shows the matrix for the chosen role with each cell at the right scope', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    renderAt('/administration/roles')

    await user.click(await screen.findByRole('button', { name: /Storekeeper/ }))

    const view = await screen.findByRole('combobox', { name: 'Financial Management: View' })
    expect(view).toHaveValue('ALL')
    expect(screen.getByRole('combobox', { name: 'Financial Management: Edit' })).toHaveValue('')
    expect(screen.getByRole('combobox', { name: 'Medical Management: View' })).toHaveValue('')
    expect(screen.getAllByRole('combobox', { name: /Medical Management/ })).toHaveLength(8)
    expect(screen.getByRole('button', { name: 'Save permissions' })).toBeDisabled()
  })

  it('saves exactly the cells that were changed and confirms', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(
      routes({
        [`PUT /rbac/roles/${STOREKEEPER.id}/grants/`]: ({ body }: { body: unknown }) => ({
          body: detail(STOREKEEPER, (body as { grants: object[] }).grants),
        }),
      }),
    )
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Storekeeper/ }))

    await user.selectOptions(
      await screen.findByRole('combobox', { name: 'Financial Management: Edit' }),
      'DEPARTMENT',
    )
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Financial Management: View' }),
      'OWN',
    )
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save permissions' }))

    expect(await screen.findByText(/Permissions saved/)).toBeInTheDocument()
    const put = calls.find((call) => call.method === 'PUT')!
    expect(put.headers.get('X-CSRFToken')).toBe('test-token')
    expect(put.body).toEqual({
      grants: [
        { module: 'finance', action: 'VIEW', scope: 'OWN' },
        { module: 'finance', action: 'EDIT', scope: 'DEPARTMENT' },
      ],
    })
    expect(screen.getByRole('button', { name: 'Save permissions' })).toBeDisabled()
  })

  it('removing access sends a smaller matrix', async () => {
    const user = userEvent.setup()
    const { calls } = mockApi(
      routes({
        [`PUT /rbac/roles/${STOREKEEPER.id}/grants/`]: { body: detail(STOREKEEPER, []) },
      }),
    )
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Storekeeper/ }))

    await user.selectOptions(
      await screen.findByRole('combobox', { name: 'Financial Management: View' }),
      '',
    )
    await user.click(screen.getByRole('button', { name: 'Save permissions' }))

    await screen.findByText(/Permissions saved/)
    expect(calls.find((call) => call.method === 'PUT')!.body).toEqual({ grants: [] })
  })

  it('discard puts every cell back', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Storekeeper/ }))

    const cell = await screen.findByRole('combobox', { name: 'Financial Management: Edit' })
    await user.selectOptions(cell, 'ALL')
    await user.click(screen.getByRole('button', { name: 'Discard changes' }))

    expect(cell).toHaveValue('')
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument()
  })

  it("shows the server's reason when a save is refused", async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        [`PUT /rbac/roles/${STOREKEEPER.id}/grants/`]: apiError(
          403,
          'self_escalation',
          'You cannot change the permissions of a role you hold yourself.',
        ),
      }),
    )
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Storekeeper/ }))
    await user.selectOptions(
      await screen.findByRole('combobox', { name: 'Financial Management: Edit' }),
      'ALL',
    )
    await user.click(screen.getByRole('button', { name: 'Save permissions' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('you hold yourself')
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument() // nothing was lost
  })

  it('asks before throwing away unsaved changes when switching roles', async () => {
    const user = userEvent.setup()
    mockApi(routes())
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Storekeeper/ }))
    await user.selectOptions(
      await screen.findByRole('combobox', { name: 'Financial Management: Edit' }),
      'ALL',
    )

    await user.click(screen.getByRole('button', { name: /Field Visitor/ }))

    expect(confirm).toHaveBeenCalled()
    expect(screen.getByRole('heading', { name: /Storekeeper/ })).toBeInTheDocument()
    confirm.mockRestore()
  })

  it('creates a role and selects it', async () => {
    const user = userEvent.setup()
    const created = { ...CUSTOM, id: 'r4444444-4444-4444-8444-444444444444', name: 'Night Nurse' }
    const { calls } = mockApi(
      routes({
        'POST /rbac/roles/': { status: 201, body: { ...created, grants: [] } },
      }),
    )
    renderAt('/administration/roles')

    await user.type(await screen.findByLabelText('New role name'), 'Night Nurse')
    await user.click(screen.getByRole('button', { name: 'Create role' }))

    expect(await screen.findByRole('heading', { name: /Night Nurse/ })).toBeInTheDocument()
    expect(calls.find((call) => call.method === 'POST')!.body).toEqual({
      name: 'Night Nurse',
      grants: [],
    })
  })

  it('built-in roles cannot be deleted from the screen; the Administrator cannot be deactivated', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        [`GET /rbac/roles/${ADMIN_ROLE.id}/`]: { body: detail(ADMIN_ROLE) },
      }),
    )
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Administrator/ }))

    await screen.findByText('Built-in')
    expect(screen.queryByRole('button', { name: 'Delete role' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Deactivate role' })).not.toBeInTheDocument()
  })

  it('deletes a custom role after confirmation', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { calls } = mockApi(
      routes({
        [`GET /rbac/roles/${CUSTOM.id}/`]: { body: detail(CUSTOM) },
        [`DELETE /rbac/roles/${CUSTOM.id}/`]: { status: 204 },
      }),
    )
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Field Visitor/ }))
    await user.click(await screen.findByRole('button', { name: 'Delete role' }))

    expect(await screen.findByText('Role deleted.')).toBeInTheDocument()
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true)
    vi.restoreAllMocks()
  })

  it('deactivating a role says what happens to its holders', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        [`PATCH /rbac/roles/${STOREKEEPER.id}/`]: {
          body: detail({ ...STOREKEEPER, is_active: false }),
        },
      }),
    )
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Storekeeper/ }))
    await user.click(await screen.findByRole('button', { name: 'Deactivate role' }))

    expect(await screen.findByText(/holders lose its permissions now/)).toBeInTheDocument()
  })

  it('is read-only for someone who may view but not manage users', async () => {
    const user = userEvent.setup()
    mockApi(
      routes({
        'GET /auth/me/': meAs({ users: { VIEW: 'ALL' } }),
      }),
    )
    renderAt('/administration/roles')
    await user.click(await screen.findByRole('button', { name: /Storekeeper/ }))

    expect(screen.getByText(/look at roles but not change them/i)).toBeInTheDocument()
    expect(
      await screen.findByRole('combobox', { name: 'Financial Management: View' }),
    ).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save permissions' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('New role name')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Role name')).toBeDisabled()
  })

  it('shows an error when roles cannot be loaded', async () => {
    mockApi({
      'GET /auth/me/': ME,
      'GET /rbac/catalogue/': apiError(500, 'server_error', 'Boom.'),
      'GET /rbac/roles/': apiError(500, 'server_error', 'Boom.'),
    })
    renderAt('/administration/roles')

    expect(await screen.findByText('Could not load roles.')).toBeInTheDocument()
  })
})
