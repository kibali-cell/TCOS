import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'
import { MODULES } from './modules'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('application shell', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: 'ok', database: 'ok' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists the dashboard and all twelve modules in the navigation', () => {
    renderAt('/')

    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    const links = within(nav).getAllByRole('link')

    expect(MODULES).toHaveLength(12)
    expect(links).toHaveLength(13)
    expect(within(nav).getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    for (const module of MODULES) {
      expect(within(nav).getByRole('link', { name: module.name })).toBeInTheDocument()
    }
  })

  it('shows no invented institutional figures on the dashboard', () => {
    renderAt('/')

    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    const text = document.body.textContent ?? ''
    for (const reference of ['85', '42', '43']) {
      expect(text).not.toContain(reference)
    }
  })

  it('shows a clear "Not yet available" page for an unbuilt module', async () => {
    const user = userEvent.setup()
    renderAt('/')

    await user.click(screen.getByRole('link', { name: 'Medical Management' }))

    expect(screen.getByRole('heading', { name: 'Medical Management' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Not yet available.')
  })

  it('shows a not-found page for an unknown module', () => {
    renderAt('/modules/does-not-exist')

    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('opens and closes the navigation drawer with the menu button and Escape', async () => {
    const user = userEvent.setup()
    renderAt('/')

    const button = screen.getByRole('button', { name: 'Open navigation' })
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

    await user.click(screen.getByRole('button', { name: 'Open navigation' }))
    await user.click(screen.getByRole('link', { name: 'Donor Management' }))

    expect(document.getElementById('sidebar')).not.toHaveClass('open')
  })
})
