import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import { FLUSH_MS } from './useMatchStream'
import { FakeEventSource } from './test/fakeEventSource'
import { alert, ARGENTINA, FRANCE, incident, matchInfo, broadcast, reset, snapshot, status } from './test/factories'

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
      case '/api/control':
        return json(status({ state: 'paused' }))
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
  window.location.hash = ''
})

it('switches to the markets with the URL, and back', async () => {
  render(<App />)
  act(() => {
    window.location.hash = '#/markets'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
  expect(screen.getByRole('link', { name: 'Markets' })).toHaveAttribute('aria-current', 'page')
  expect(screen.queryByRole('region', { name: 'Charts' })).toBeNull()
  expect(await screen.findByRole('group', { name: 'League' })).toBeInTheDocument()
  act(() => {
    window.location.hash = '#/'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
  expect(screen.getByRole('region', { name: 'Charts' })).toBeInTheDocument()
})

/** Waits for the stream's messages to be applied. */
const applied = () => act(() => new Promise((resolve) => setTimeout(resolve, FLUSH_MS * 2)))

it('renders the layout', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Live Football Analytics' })).toBeInTheDocument()
  const pages = screen.getByRole('navigation', { name: 'Pages' })
  expect(within(pages).getByRole('link', { name: 'Match analytics' })).toHaveAttribute('aria-current', 'page')
  expect(within(pages).getByRole('link', { name: 'Markets' })).toHaveAttribute('href', '#/markets')
  const simulator = screen.getByRole('region', { name: 'Simulator' })
  expect(simulator).toHaveAccessibleDescription(/Stands in for the live feed/)
  expect(within(simulator).getByRole('group', { name: 'Broadcast' })).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Controls' })).getByRole('group', { name: 'Viewer' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Charts' })).toBeInTheDocument()
  expect(screen.getByRole('complementary', { name: 'Match feed' })).toBeInTheDocument()
})

const broadcastCommands = () =>
  fetch.mock.calls
    .filter(([url, init]) => url === '/api/broadcast' && init?.method === 'POST')
    .map(([, init]) => JSON.parse(init?.body as string) as unknown)

it('loads a match through the engine and starts its broadcast, which enables the controls', async () => {
  render(<App />)
  const broadcastBar = screen.getByRole('group', { name: 'Broadcast' })
  expect(within(broadcastBar).getByRole('button', { name: 'Play' })).toBeDisabled()

  await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Match' }), '3869685')
  expect(await within(broadcastBar).findByRole('button', { name: 'Play' })).toBeEnabled()
  await vi.waitFor(() =>
    expect(broadcastCommands()).toEqual([
      { schema_version: 1, command: 'load_match', match_id: 3869685 },
      { schema_version: 1, command: 'play' },
    ]),
  )
})

it('does not start the broadcast if the match fails to load', async () => {
  const ok = fetch.getMockImplementation()!
  fetch.mockImplementation((url, init) =>
    url === '/api/broadcast' && init?.method === 'POST' ? json({ error: 'no such match' }, 404) : ok(url, init),
  )
  render(<App />)
  await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Match' }), '3869685')
  expect(await screen.findByRole('alert')).toHaveTextContent('no such match')
  expect(broadcastCommands()).toEqual([{ schema_version: 1, command: 'load_match', match_id: 3869685 }])
})

it('hides the simulator when the engine has none, as with a real feed', async () => {
  const noSimulator = json({ error: "no simulator: this feed can't be controlled from here" }, 404)
  const ok = fetch.getMockImplementation()!
  fetch.mockImplementation((url, init) =>
    url === '/api/broadcast' || url === '/api/matches' ? noSimulator : ok(url, init),
  )
  render(<App />)
  expect(await screen.findByText('No match yet. Waiting for the feed to start one…')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Simulator' })).toBeNull()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByRole('group', { name: 'Viewer' })).toBeInTheDocument()
})

it('shows the error when the engine is down', async () => {
  fetch.mockImplementation(() => Promise.resolve(new Response('Bad Gateway', { status: 502 })))
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('engine unavailable')
})

it('shows the stream on the scoreboard, timeline, charts and match feed', async () => {
  render(<App />)
  await screen.findByRole('combobox', { name: 'Match' })
  const stream = FakeEventSource.instances[0]
  expect(screen.getByRole('status')).toHaveTextContent('Connecting…')
  act(() => {
    stream.open()
    stream.send('reset', reset())
    stream.send(
      'status',
      status({
        state: 'live',
        period: 2,
        match_clock_s: 82 * 60 + 7,
        score: [
          { team_id: ARGENTINA.id, goals: 2 },
          { team_id: FRANCE.id, goals: 1 },
        ],
      }),
    )
    stream.send('snapshot', snapshot(2, 82 * 60))
    stream.send('incident', incident())
    stream.send('alert', alert())
  })
  await applied()
  expect(screen.getByRole('status')).toHaveTextContent('Connected Live')
  const board = within(screen.getByRole('region', { name: 'Charts' })).getByRole('region', { name: 'Scoreboard' })
  expect(board).toHaveTextContent('Score: Argentina 2, France 1')
  expect(board).toHaveTextContent('82:072nd half')
  expect(screen.getAllByRole('figure').map((f) => f.getAttribute('aria-label'))).toEqual([
    'Match timeline',
    'Field tilt',
    'xT added',
    'Pressure index',
  ])
  const feed = within(screen.getByRole('complementary', { name: 'Match feed' })).getAllByRole('listitem')
  expect(feed.map((li) => li.textContent)).toEqual([
    "82:27· ControlWatching · 10' leftFrance taking control: pressure balance +0.69 over the last 5', from -0.54 the 5' before",
    '35:22· Argentina2–0Goal · Ángel Di María',
  ])
})

it('drives the viewer through the engine, which shows on the stream', async () => {
  render(<App />)
  const viewerBar = screen.getByRole('group', { name: 'Viewer' })
  expect(within(viewerBar).getByRole('button', { name: 'Play' })).toBeDisabled()
  const stream = FakeEventSource.instances[0]
  const edge = { offset: 2000, period: 2, match_clock_s: 70 * 60, play_s: 70 * 60 }
  act(() => {
    stream.open()
    stream.send('status', status({ state: 'live', live_edge: edge, behind_live_s: 0, speed: 1 }))
  })
  await applied()
  expect(viewerBar).toHaveTextContent('LIVE')

  await userEvent.click(within(viewerBar).getByRole('button', { name: 'Pause' }))
  const [, init] = fetch.mock.calls.find(([url]) => url === '/api/control')!
  expect(JSON.parse(init?.body as string)).toEqual({ schema_version: 1, command: 'pause' })
  act(() => stream.send('status', status({ state: 'paused', live_edge: edge, behind_live_s: 65, speed: 1 })))
  await applied()
  expect(viewerBar).toHaveTextContent('1:05 behind live')
  expect(within(viewerBar).getByRole('button', { name: 'Go live' })).toBeEnabled()
})
