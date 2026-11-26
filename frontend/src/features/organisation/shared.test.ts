import { afterEach, describe, expect, it } from 'vitest'

import { mockApi } from '../../test/mockApi'
import { fetchAll } from './shared'

afterEach(() => undefined)

describe('fetchAll', () => {
  it('follows every page and stops at the last', async () => {
    const { calls } = mockApi({
      'GET /things/?page_size=2': {
        body: { count: 3, next: 'x', previous: null, results: [1, 2] },
      },
      'GET /things/?page_size=2&page=2': {
        body: { count: 3, next: null, previous: 'x', results: [3] },
      },
    })
    expect(await fetchAll<number>('/things/?page_size=2')).toEqual([1, 2, 3])
    expect(calls).toHaveLength(2)
  })

  it('stops at its page limit rather than looping forever', async () => {
    mockApi({
      'GET /loop/': { body: { count: 1, next: 'x', previous: null, results: [1] } },
      'GET /loop/?page=2': { body: { count: 1, next: 'x', previous: null, results: [1] } },
    })
    expect(await fetchAll<number>('/loop/', 2)).toEqual([1, 1])
  })
})
