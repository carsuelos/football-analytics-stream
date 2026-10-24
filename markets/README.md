# markets

The prediction markets' prices for our leagues' games (Premier League, La Liga): which games Kalshi, Polymarket US and Novig list, each venue's price for the same contracts, and the cheapest all-in. It's the dashboard's **Markets** page, and where paper trading will live.

```sh
make markets    # :8090; make dashboard proxies /api/markets to it
curl 'localhost:8090/api/markets/board?league=epl'
```

It reads only the venues' public market data, so it needs no keys.

## How it works

| Path | What |
| --- | --- |
| `internal/venue` | What every venue gives: a league's `Event`s (a game: teams, kick-off, live state if known) with `Quote`s (the Yes bid and ask per contract, and the venue's taker-fee schedule) |
| `internal/kalshi` | Kalshi: the total-goals and result series (`KXEPLTOTAL`, `KXEPLGAME`, `KXLALIGATOTAL`, `KXLALIGAGAME`), joined into games by their tickers. No kick-off time, so it's estimated from when the markets close |
| `internal/polymarket` | Polymarket US: each game's result markets (it lists no per-game totals yet), and the **live score and clock** from its sports data |
| `internal/novig` | Novig's public catalog: total goals and the result. It lists bids on both sides, so the Yes ask is 1 − the No bid. Its contracts pay 1¢, so its sizes are divided by 100; its fee is charged only in-game |
| `internal/teams` | Whether two venues' names are the same team ("Bilbao", "Athletic Club", "Athletic Club Bilbao") |
| `internal/board` | Polls the venues (every 10 s for a league someone is looking at, every 2 min otherwise), matches each game across them (same teams, kick-offs within 30 h), prices every contract (all-in = ask + fee) and marks the cheapest with contracts at its ask. A failing venue keeps its last games for 2 minutes. Keeps each game's best all-in price over time for 6 hours, in memory |
| `internal/server` | `GET /api/markets/board?league=epl\|laliga` (a `MarketBoard`), `GET /api/markets/games/{id}/history` (a `PriceHistory`), `GET /healthz` |
| `internal/schema` | Generated from `schema/jsonschema/` by `make gen`; do not edit |

The contracts compared are the ones each venue settles the same way: **total goals** (over a line after 90' plus stoppage time) and the **result** after 90' plus stoppage time. Taker fees per contract at price p: Kalshi 0.07 · p(1 − p), Polymarket 0.0695 · p(1 − p), Novig 0.06 · p(1 − p) once the game is live.
