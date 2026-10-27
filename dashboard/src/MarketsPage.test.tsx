import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { BOARD_POLL_MS, MarketsPage } from './MarketsPage'
import type { MarketBoard } from './schema/market_board.schema'
import { marketBoard } from './test/factories'

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

let fetch: ReturnType<typeof vi.fn<typeof globalThis.fetch>>
let board: MarketBoard

beforeEach(() => {
  board = marketBoard()
  fetch = vi.fn<typeof globalThis.fetch>((input) => {
    const url = String(input)
    if (url.startsWith('/api/markets/board')) {
      const league = new URL(url, 'http://x').searchParams.get('league')
      return json(league !== 'epl' ? { ...board, league, games: [] } : board)
    }
    if (url === '/api/markets/games/epl-2026-10-24-chelsea-tottenham/history') {
      return json({
        schema_version: 1,
        game_id: 'epl-2026-10-24-chelsea-tottenham',
        series: [{ key: 'total-over-1.5', points: [{ t: '2026-10-24T17:50:00Z', all_in: 0.16, venue: 'kalshi' }] }],
      })
    }
    return json({ error: 'not found' }, 404)
  })
  vi.stubGlobal('fetch', fetch)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('shows the venues, the games and the live game first', async () => {
  render(<MarketsPage />)
  const venues = await screen.findByRole('list', { name: 'Venues' })
  expect(venues).toHaveTextContent('Kalshi2 games')
  expect(within(venues).getAllByRole('listitem')[2]).toHaveTextContent('Novig1 games · 3m ago · failing')
  const games = screen.getByRole('navigation', { name: 'Games' })
  const live = within(games).getByRole('region', { name: 'Live' })
  expect(live).toHaveTextContent("63'Chelsea1Tottenham0")
  expect(within(live).getByRole('button')).toHaveAttribute('aria-current', 'true')
  expect(within(live).getByLabelText('Listed on Polymarket, Novig, Kalshi')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Game' })).toHaveTextContent('Score: Chelsea 1, Tottenham 0')
})

it('prices each contract on each venue and marks the cheapest all-in', async () => {
  render(<MarketsPage />)
  const totals = await screen.findByRole('region', { name: 'Total goals' })
  const [, over05, over15] = within(totals).getAllByRole('row')
  expect(over05).toHaveTextContent('Over 0.5already over')
  const cells = within(over15).getAllByRole('cell')
  expect(cells.map((c) => c.textContent)).toEqual(['48¢bid 47¢ · fee 1.7¢', '—', '49¢bid 47¢', '49¢49% · Novig', '—'])
  expect(cells[2].querySelector('[title="Cheapest all-in"]')).not.toBeNull()
  expect(cells[0].querySelector('[title="Cheapest all-in"]')).toBeNull()
  const result = screen.getByRole('region', { name: 'Result' })
  expect(within(result).getAllByRole('row')[1]).toHaveTextContent('Draw—23¢bid 22¢ · fee 1.2¢—24.2¢24% · Polymarket—')
})

it("prices each team's goals, and folds a kind of contract away until it's opened again", async () => {
  render(<MarketsPage />)
  const teams = await screen.findByRole('region', { name: 'Team goals' })
  const [, home, away] = within(teams).getAllByRole('row')
  expect(home).toHaveTextContent('Chelsea over 0.5already over')
  expect(away).toHaveTextContent('Tottenham over 0.5')
  expect(away).not.toHaveTextContent('already over')
  expect(within(away).getAllByRole('cell')[3]).toHaveTextContent('33.5¢34% · Kalshi')

  const toggle = within(teams).getByRole('button', { name: 'Team goals 2 contracts' })
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(within(teams).queryByRole('table')).toBeNull()
  // Still folded on the next visit.
  expect(localStorage.getItem('markets.open.Team goals')).toBe('0')
  await userEvent.click(toggle)
  expect(within(teams).getByRole('table')).toBeInTheDocument()
})

it('follows the contract the market is least sure of, or the one clicked', async () => {
  render(<MarketsPage />)
  const chart = await screen.findByRole('region', { name: 'Price over time' })
  expect(chart).toHaveTextContent('Best all-in price · Over 1.5')
  await userEvent.click(within(screen.getByRole('region', { name: 'Result' })).getByText('Draw'))
  expect(chart).toHaveTextContent('Best all-in price · Draw')
})

it('switches games and leagues', async () => {
  render(<MarketsPage />)
  await userEvent.click(await screen.findByRole('button', { name: /Crystal Palace/ }))
  expect(screen.getByRole('region', { name: 'Game' })).toHaveTextContent('(est.)')
  expect(screen.getByRole('region', { name: 'Total goals' })).toHaveTextContent('No venue lists these for this game.')
  await userEvent.click(screen.getByRole('button', { name: 'La Liga' }))
  expect(await screen.findByText('No games listed right now.')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/markets/board?league=laliga', expect.anything())
  await userEvent.click(screen.getByRole('button', { name: 'MLS' }))
  expect(fetch).toHaveBeenCalledWith('/api/markets/board?league=mls', expect.anything())
  await userEvent.click(screen.getByRole('button', { name: 'Champions League' }))
  expect(fetch).toHaveBeenCalledWith('/api/markets/board?league=ucl', expect.anything())
})

it('keeps the last prices on screen while the service is unreachable, and polls on', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  render(<MarketsPage />)
  await screen.findByRole('region', { name: 'Total goals' })
  fetch.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')))
  await act(() => vi.advanceTimersByTimeAsync(BOARD_POLL_MS))
  expect(screen.getByRole('alert')).toHaveTextContent('markets service unavailable (showing the last prices)')
  expect(screen.getByRole('region', { name: 'Total goals' })).toBeInTheDocument()
})

it('shows how it will trade, on paper or with real money, all off until the live feed', async () => {
  render(<MarketsPage />)
  const trading = await screen.findByRole('region', { name: 'Trading' })
  expect(trading).toHaveTextContent('Off until the live feed')
  expect(within(trading).getByRole('group', { name: 'Strategy' })).toBeDisabled()
  expect(within(trading).getByRole('combobox', { name: 'Buy' })).toHaveValue('best')
  expect(within(trading).getByRole('button', { name: 'Start paper trading' })).toBeDisabled()
  expect(within(trading).queryByRole('group', { name: 'Venue keys' })).toBeNull()

  await userEvent.click(within(trading).getByRole('button', { name: 'Real money' }))
  const keys = within(trading).getByRole('group', { name: 'Venue keys' })
  expect(keys).toBeDisabled()
  expect(within(trading).getByRole('note')).toHaveTextContent('Runs only on your own machine')
  for (const venue of ['Kalshi', 'Polymarket', 'Novig']) expect(within(keys).getByRole('group', { name: `${venue} key` })).toBeInTheDocument()
  expect(within(keys).getByLabelText('Private key (RSA, PEM)')).toHaveAttribute('type', 'password')
  expect(within(keys).getAllByRole('link', { name: /Create one/ }).map((a) => a.getAttribute('href'))).toEqual([
    'https://kalshi.com/account/profile',
    'https://polymarket.us/developer',
    'https://novig.com/Profile/ProfileScreen',
  ])
  expect(within(keys).getByRole('button', { name: 'Start real trading' })).toBeDisabled()
})

const sections = () => screen.getAllByRole('region').map((r) => r.getAttribute('aria-label')).filter((n) => ['Result', 'Total goals', 'Team goals'].includes(n!))

it('orders the sections result, total goals, team goals, and moves them by their handles', async () => {
  render(<MarketsPage />)
  await screen.findByRole('region', { name: 'Result' })
  expect(sections()).toEqual(['Result', 'Total goals', 'Team goals'])

  // With the keyboard: focus a handle, then the arrow keys.
  screen.getByRole('button', { name: 'Move Team goals' }).focus()
  await userEvent.keyboard('{ArrowUp}')
  expect(sections()).toEqual(['Result', 'Team goals', 'Total goals'])
  await userEvent.keyboard('{Home}')
  expect(sections()).toEqual(['Team goals', 'Result', 'Total goals'])
  expect(JSON.parse(localStorage.getItem('markets.sections')!)).toEqual(['team_total', 'result', 'total'])

  // By dragging a handle onto another section.
  const dataTransfer = { setData: vi.fn(), setDragImage: vi.fn(), effectAllowed: '' }
  fireEvent.dragStart(screen.getByRole('button', { name: 'Move Total goals' }), { dataTransfer })
  fireEvent.dragOver(screen.getByRole('region', { name: 'Team goals' }), { dataTransfer })
  fireEvent.drop(screen.getByRole('region', { name: 'Team goals' }), { dataTransfer })
  expect(sections()).toEqual(['Total goals', 'Team goals', 'Result'])
})

it('keeps a stored order, with any new kind of contract at the end', async () => {
  localStorage.setItem('markets.sections', JSON.stringify(['team_total', 'gone', 'total']))
  render(<MarketsPage />)
  await screen.findByRole('region', { name: 'Result' })
  expect(sections()).toEqual(['Team goals', 'Total goals', 'Result'])
})
