import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AddMatches } from './MatchLibrary'
import type { LibraryDownload, MatchLibrary } from './schema/match_library.schema'

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

const EURO = { competition_id: 53, season_id: 315, competition: "UEFA Women's Euro", season: '2025', country: 'Europe', gender: 'female', downloaded: 0 } as const
const WORLD_CUP = { competition_id: 43, season_id: 106, competition: 'FIFA World Cup', season: '2022', country: 'International', gender: 'male', downloaded: 64, matches: 64 } as const
const progress = (state: LibraryDownload['state'], done: number): LibraryDownload => ({
  competition_id: 53, season_id: 315, competition: "UEFA Women's Euro", season: '2025', state, done, total: 31,
}) // prettier-ignore

let library: MatchLibrary
let fetch: ReturnType<typeof vi.fn<typeof globalThis.fetch>>

beforeEach(() => {
  library = { schema_version: 1, seasons: [EURO, WORLD_CUP] }
  fetch = vi.fn<typeof globalThis.fetch>((url, init) => {
    if (url === '/api/library' && init?.method === 'POST') {
      library = { ...library, download: progress('downloading', 3) }
      return json(library, 202)
    }
    if (url === '/api/library') return json(library)
    return json({ error: 'not found' }, 404)
  })
  vi.stubGlobal('fetch', fetch)
})

afterEach(() => vi.unstubAllGlobals())

it("lists StatsBomb's seasons, filtered by a search and by women's or men's", async () => {
  render(<AddMatches onDownloaded={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: '+ Add matches' }))
  const dialog = screen.getByRole('dialog', { name: 'Add matches' })
  const seasons = await within(dialog).findByRole('list', { name: 'Seasons' })
  await waitFor(() => expect(within(seasons).getAllByRole('listitem')).toHaveLength(2))
  expect(within(seasons).getAllByRole('listitem')[1]).toHaveTextContent('FIFA World Cup 2022International · Men\'s · 64 of 64 matches downloadedDownloaded ✓')
  await userEvent.type(within(dialog).getByRole('searchbox', { name: 'Search' }), 'euro 2025')
  expect(within(seasons).getAllByRole('listitem')).toHaveLength(1)
  await userEvent.clear(within(dialog).getByRole('searchbox', { name: 'Search' }))
  await userEvent.click(within(dialog).getByRole('button', { name: "Men's" }))
  expect(within(seasons).getAllByRole('listitem').map((li) => li.textContent)).toEqual([expect.stringContaining('FIFA World Cup')])
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('downloads a season, shows its progress, and refreshes the match list when it ends', async () => {
  const onDownloaded = vi.fn()
  render(<AddMatches onDownloaded={onDownloaded} />)
  await userEvent.click(screen.getByRole('button', { name: '+ Add matches' }))
  await userEvent.click(await screen.findByRole('button', { name: "Download UEFA Women's Euro 2025" }))
  expect(JSON.parse(fetch.mock.calls.find(([, init]) => init?.method === 'POST')![1]!.body as string)).toEqual({ schema_version: 1, competition_id: 53, season_id: 315 })
  expect(screen.getByRole('status')).toHaveTextContent("Downloading UEFA Women's Euro 2025: 3 of 31 matches")
  expect(screen.getByRole('button', { name: "Download UEFA Women's Euro 2025" })).toBeDisabled()
  library = { schema_version: 1, seasons: [{ ...EURO, downloaded: 31, matches: 31 }, WORLD_CUP], download: progress('done', 31) }
  await waitFor(() => expect(onDownloaded).toHaveBeenCalledOnce(), { timeout: 3000 })
  expect(screen.getByRole('status')).toHaveTextContent('now in the match list')
  expect(screen.queryByRole('button', { name: /Download UEFA/ })).toBeNull()
})

it("says when StatsBomb couldn't be reached, or a download is already running", async () => {
  library = { schema_version: 1, seasons: [EURO], error: 'statsbomb: 503 Service Unavailable' }
  fetch
    .mockImplementationOnce(() => json(library)) // is it offered?
    .mockImplementationOnce(() => json(library)) // the dialog
    .mockImplementationOnce(() => json({ error: 'a download is already running' }, 409))
  render(<AddMatches onDownloaded={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: '+ Add matches' }))
  expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't refresh the list from StatsBomb: statsbomb: 503")
  await userEvent.click(screen.getByRole('button', { name: "Download UEFA Women's Euro 2025" }))
  expect(await screen.findByRole('alert')).toHaveTextContent('a download is already running')
})

it("isn't offered where the simulator can't download", async () => {
  fetch.mockImplementation(() => json({ error: "this simulator can't download matches" }, 404))
  render(<AddMatches onDownloaded={() => {}} />)
  await waitFor(() => expect(screen.queryByRole('button', { name: '+ Add matches' })).toBeNull())
})
