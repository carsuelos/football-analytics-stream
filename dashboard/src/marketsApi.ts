import { ApiError } from './api'
import type { League, MarketBoard } from './schema/market_board.schema'
import type { PriceHistory } from './schema/price_history.schema'

/** A league's games and prices on the prediction markets. */
export const getBoard = (league: League, signal?: AbortSignal) =>
  get<MarketBoard>(`/api/markets/board?league=${league}`, signal)

/** A game's best all-in prices since the markets service started watching it. */
export const getHistory = (gameId: string, signal?: AbortSignal) =>
  get<PriceHistory>(`/api/markets/games/${encodeURIComponent(gameId)}/history`, signal)

async function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, { signal })
  } catch (e) {
    if (signal?.aborted) throw e
    throw new ApiError('markets service unavailable', 0)
  }
  const body: unknown = await res.json().catch(() => undefined)
  if (res.ok && body !== undefined) return body as T
  if (typeof body === 'object' && body !== null && typeof (body as { error?: unknown }).error === 'string') {
    throw new ApiError((body as { error: string }).error, res.status)
  }
  throw new ApiError(res.status >= 500 ? 'markets service unavailable' : `unexpected reply (HTTP ${res.status})`, res.status)
}
