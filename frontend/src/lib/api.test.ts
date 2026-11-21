import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from './api'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function clearCsrfCookie() {
  document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
}

describe('api client', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    clearCsrfCookie()
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
    clearCsrfCookie()
  })

  it('sends GET requests same-origin without a CSRF header', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }))

    await api('/health/')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/health/')
    expect(init.credentials).toBe('same-origin')
    expect(init.headers['X-CSRFToken']).toBeUndefined()
  })

  it('uses an existing CSRF cookie for unsafe methods without an extra request', async () => {
    document.cookie = 'csrftoken=abc123; path=/'
    fetchMock.mockResolvedValueOnce(jsonResponse({ done: true }))

    await api('/things/', { method: 'POST', body: { name: 'x' } })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['X-CSRFToken']).toBe('abc123')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ name: 'x' }))
  })

  it('fetches the CSRF cookie first when it is missing', async () => {
    fetchMock.mockImplementationOnce(async () => {
      document.cookie = 'csrftoken=fresh456; path=/'
      return jsonResponse({ detail: 'CSRF cookie set.' })
    })
    fetchMock.mockResolvedValueOnce(jsonResponse({ done: true }))

    await api('/things/', { method: 'DELETE' })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/csrf/')
    expect(fetchMock.mock.calls[1][1].headers['X-CSRFToken']).toBe('fresh456')
  })

  it('fails clearly when no CSRF token can be obtained', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'no cookie' }))

    await expect(api('/things/', { method: 'POST', body: {} })).rejects.toMatchObject({
      code: 'csrf_unavailable',
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('turns the backend error envelope into an ApiError', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: 'validation_error',
            message: 'The submitted data is not valid.',
            details: { name: ['This field is required.'] },
          },
        },
        400,
      ),
    )

    const failure = await api('/things/').catch((error: unknown) => error)

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure).toMatchObject({
      status: 400,
      code: 'validation_error',
      message: 'The submitted data is not valid.',
      details: { name: ['This field is required.'] },
    })
  })

  it('gives a generic ApiError when an error response is not JSON', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>Bad gateway</html>', { status: 502 }))

    await expect(api('/things/')).rejects.toMatchObject({ status: 502, code: 'error' })
  })

  it('reports network failures as status 0', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(api('/things/')).rejects.toMatchObject({ status: 0, code: 'network_error' })
  })

  it('returns undefined for 204 responses', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))

    await expect(api('/things/')).resolves.toBeUndefined()
  })
})
