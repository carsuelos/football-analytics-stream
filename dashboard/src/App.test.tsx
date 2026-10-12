import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import { FakeEventSource } from './test/fakeEventSource'
import { matchInfo, playback } from './test/factories'

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

let fetch: ReturnType<typeof vi.fn<typeof globalThis.fetch>>

beforeEach(() => {
  vi.stubGlobal('EventSource', FakeEventSource)
  fetch = vi.fn<typeof globalThis.fetch>((url) => {
    switch (url) {
      case '/api/matches':
        return json({ schema_version: 1, matches: [matchInfo()] })
      case '/api/playback':
        return json(playback({ state: 'idle', match_id: undefined }))
      case '/api/control':
        return json(playback({ state: 'paused' }))
      default:
        return json({ error: 'not found' }, 404)
    }
  })
  vi.stubGlobal('fetch', fetch)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

it('renders the layout', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Live Football Analytics' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Playback' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Charts' })).toBeInTheDocument()
  expect(screen.getByRole('complementary', { name: 'Alerts' })).toBeInTheDocument()
})

it('loads a match through the engine, which enables the controls', async () => {
  render(<App />)
  const playbackBar = screen.getByRole('region', { name: 'Playback' })
  expect(within(playbackBar).getByRole('button', { name: 'Play' })).toBeDisabled()

  await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Match' }), '3869685')
  expect(await within(playbackBar).findByRole('button', { name: 'Play' })).toBeEnabled()
  const [, init] = fetch.mock.calls.find(([url]) => url === '/api/control')!
  expect(JSON.parse(init?.body as string)).toEqual({ schema_version: 1, command: 'load_match', match_id: 3869685 })
})

it('shows the error when the engine is down', async () => {
  fetch.mockImplementation(() => Promise.resolve(new Response('Bad Gateway', { status: 502 })))
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('engine unavailable')
})
