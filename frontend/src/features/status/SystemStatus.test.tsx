import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SystemStatus } from './SystemStatus'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('SystemStatus', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
  })

  it('shows a loading state first, then success when the server reports ok', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'ok', database: 'ok' }))

    render(<SystemStatus />)

    expect(screen.getByText('Checking…')).toBeInTheDocument()
    expect(await screen.findByText('Server and database are reachable.')).toBeInTheDocument()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/health/')
  })

  it('shows a database error when the server answers 503', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'error', database: 'unavailable' }, 503))

    render(<SystemStatus />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The server is running but the database is unavailable.',
    )
  })

  it('shows an unreachable error when the network fails', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    render(<SystemStatus />)

    expect(await screen.findByRole('alert')).toHaveTextContent('The server could not be reached.')
  })
})
