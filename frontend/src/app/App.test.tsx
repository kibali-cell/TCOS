import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'
import { AuthProvider } from '../features/auth/AuthContext'
import { ME, mockApi } from '../test/mockApi'
import { MODULES } from './modules'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('application shell', () => {
  beforeEach(() => {
    mockApi({
      'GET /auth/me/': ME,
      'GET /health/': { body: { status: 'ok', database: 'ok' } },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists the dashboard, all twelve modules and the roles screen for someone with full access', async () => {
    renderAt('/')

    const nav = await screen.findByRole('navigation', {
      name: 'Main navigation',
    })
    const links = within(nav).getAllByRole('link')

    expect(MODULES).toHaveLength(12)
    expect(links).toHaveLength(15) // dashboard, twelve modules, roles, organisation
    expect(within(nav).getByRole('link', { name: 'Organisation' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    for (const module of MODULES) {
      expect(within(nav).getByRole('link', { name: module.name })).toBeInTheDocument()
    }
  })

  it('shows no invented institutional figures on the dashboard', async () => {
    renderAt('/')

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    const text = document.body.textContent ?? ''
    for (const reference of ['85', '42', '43']) {
      expect(text).not.toContain(reference)
    }
  })

  it('shows a clear "Not yet available" page for an unbuilt module', async () => {
    const user = userEvent.setup()
    renderAt('/')

    await user.click(await screen.findByRole('link', { name: 'Medical Management' }))

    expect(screen.getByRole('heading', { name: 'Medical Management' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Not yet available.')
  })

  it('shows a not-found page for an unknown module', async () => {
    renderAt('/modules/does-not-exist')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('opens and closes the navigation drawer with the menu button and Escape', async () => {
    const user = userEvent.setup()
    renderAt('/')

    const button = await screen.findByRole('button', {
      name: 'Open navigation',
    })
    expect(button).toHaveAttribute('aria-expanded', 'false')

    await user.click(button)
    const openButton = screen.getByRole('button', { name: 'Close navigation' })
    expect(openButton).toHaveAttribute('aria-expanded', 'true')
    expect(document.getElementById('sidebar')).toHaveClass('open')

    await user.keyboard('{Escape}')
    expect(screen.getByRole('button', { name: 'Open navigation' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('closes the drawer when a navigation link is chosen', async () => {
    const user = userEvent.setup()
    renderAt('/')

    await user.click(await screen.findByRole('button', { name: 'Open navigation' }))
    await user.click(screen.getByRole('link', { name: 'Donor Management' }))

    expect(document.getElementById('sidebar')).not.toHaveClass('open')
  })
})
