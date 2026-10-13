# dashboard

React + Vite + TypeScript dashboard: live metric charts, alerts and playback controls for the match the engine is following.

```sh
pnpm dev     # or `make dashboard` from the repo root; http://localhost:5173
pnpm test    # vitest: schema contract tests (node) and UI tests (jsdom)
pnpm lint && pnpm typecheck
```

It only talks to the engine, through `/api`. In development Vite proxies `/api` to `http://localhost:8000` (set `ENGINE_URL` to change it), so the engine needs no CORS.

| Path | Does |
| --- | --- |
| `src/App.tsx` | Page layout; wires the stream and broadcast hooks to the components |
| `src/api.ts` | Typed client for `/api/matches` and `GET`/`POST /api/broadcast`; failures throw `ApiError` (the engine's `{"error": ...}` message, or "engine unavailable") |
| `src/matchState.ts` | `matchReducer`: a pure function that builds the match (status, snapshots, alerts) from stream events; a `reset` starts it over |
| `src/useMatchStream.ts` | `useMatchStream`: follows `/api/stream` with `EventSource` and the reducer, and reconnects when the browser gives up |
| `src/useBroadcast.ts` | `useBroadcast`: the match list and the simulator's broadcast status, from each command's reply plus a fetch on load and whenever the engine's state changes; ignores replies a later request has overtaken |
| `src/MatchPicker.tsx` | Chooses the match to load (named without its score) |
| `src/BroadcastControls.tsx` | The broadcast's play/pause and speed presets (1×, 10×, 30×, 60×) |
| `src/timeline.ts` | The charts' time axis: minutes played, each period starting where the previous one ended (stoppage time overlaps the next period's clock), labelled as match minutes ("45+3'"); `matchMinute` labels a single moment the same way |
| `src/chartData.ts` | Snapshots for one window as chart points, home first; `matchTeams` takes home and away from the match list |
| `src/MetricCharts.tsx` | Field tilt (stacked to 100%), xT added and pressure per team, with a 5'/10' window toggle, period starts and alerts marked |
| `src/AlertFeed.tsx` | The match's alerts, latest in the match first, with their minute, type and team colour |
| `src/StatusBar.tsx` | The stream's connection, the engine's state and the match clock; the last state stays on screen, dimmed, while reconnecting |
| `src/ui.ts` | Shared Tailwind classes |
| `src/index.css` | Tailwind CSS entry point and theme (team colours) |
| `src/test/` | UI test setup (Testing Library matchers and cleanup) factories for API and stream messages, and a fake `EventSource` |
| `test/` | Contract tests: the shared schema fixtures against the JSON Schemas |

`src/schema/` is generated from `schema/jsonschema/` by `make gen`. Do not edit it by hand.
