import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import { FakeEventSource } from './test/fakeEventSource'
import { alert, matchInfo, broadcast, reset, snapshot, status } from './test/factories'

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

let fetch: ReturnType<typeof vi.fn<typeof globalThis.fetch>>

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  fetch = vi.fn<typeof globalThis.fetch>((url, init) => {
    switch (url) {
      case '/api/matches':
        return json({ schema_version: 1, matches: [matchInfo()] })
      case '/api/broadcast':
        return init?.method === 'POST'
          ? json(broadcast({ state: 'paused' }))
          : json(broadcast({ state: 'idle', match_id: undefined }))
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
  const [, init] = fetch.mock.calls.find(([url, init]) => url === '/api/broadcast' && init?.method === 'POST')!
  expect(JSON.parse(init?.body as string)).toEqual({ schema_version: 1, command: 'load_match', match_id: 3869685 })
})

it('shows the error when the engine is down', async () => {
  fetch.mockImplementation(() => Promise.resolve(new Response('Bad Gateway', { status: 502 })))
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('engine unavailable')
})

it('shows the stream in the status bar, charts and alert feed', async () => {
  render(<App />)
  await screen.findByRole('combobox', { name: 'Match' })
  const stream = FakeEventSource.instances[0]
  expect(screen.getByRole('status')).toHaveTextContent('Connecting…')
  act(() => {
    stream.open()
    stream.send('reset', reset())
    stream.send('status', status({ state: 'live', period: 2, match_clock_s: 82 * 60 }))
    stream.send('snapshot', snapshot(2, 82 * 60))
    stream.send('alert', alert())
  })
  expect(screen.getByRole('status')).toHaveTextContent('Connected Live')
  expect(screen.getByRole('banner')).toHaveTextContent("82' · 2nd half")
  expect(screen.getAllByRole('figure')).toHaveLength(3)
  expect(within(screen.getByRole('complementary', { name: 'Alerts' })).getByRole('listitem')).toHaveTextContent(
    "82' · Control shiftFrance taking control",
  )
})
