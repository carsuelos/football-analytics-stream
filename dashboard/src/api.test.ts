import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getMatches, getBroadcast, sendCommand } from './api'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function stubFetch(reply: Response | Error) {
  const fetch = vi.fn<typeof globalThis.fetch>(() => (reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply)))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

afterEach(() => {
  vi.unstubAllGlobals()
})

const BROADCAST = { schema_version: 1, state: 'paused', speed: 1, match_id: 3869685 }

describe('api', () => {
  it('gets the match list and the broadcast status', async () => {
    const matches = { schema_version: 1, matches: [] }
    const fetch = stubFetch(json(matches))
    expect(await getMatches()).toEqual(matches)
    expect(fetch).toHaveBeenCalledWith('/api/matches', undefined)

    stubFetch(json(BROADCAST))
    expect(await getBroadcast()).toEqual(BROADCAST)
  })

  it('posts a command as JSON, with the schema version', async () => {
    const fetch = stubFetch(json(BROADCAST))
    expect(await sendCommand({ command: 'load_match', match_id: 3869685 })).toEqual(BROADCAST)
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/broadcast')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init?.body as string)).toEqual({ schema_version: 1, command: 'load_match', match_id: 3869685 })
  })

  it.each([
    ['an error from the engine or simulator', json({ error: 'no match loaded' }, 409), 'no match loaded', 409],
    ['an unreachable engine', new TypeError('Failed to fetch'), 'engine unavailable', 0],
    ['a 5xx without an error body (the dev proxy)', new Response('', { status: 502 }), 'engine unavailable', 502],
    ['a 4xx without an error body', new Response('nope', { status: 404 }), 'unexpected reply (HTTP 404)', 404],
    ['a JSON body that is not an error', json({ detail: 'Not Found' }, 404), 'unexpected reply (HTTP 404)', 404],
    ['a 200 that is not JSON', new Response('<html>', { status: 200 }), 'unexpected reply (HTTP 200)', 200],
  ])('throws an ApiError on %s', async (_, reply, message, status) => {
    stubFetch(reply)
    const err = await getBroadcast().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ message, status })
  })
})
