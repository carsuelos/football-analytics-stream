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
| `src/App.tsx` | Page layout; wires the stream, broadcast and viewer hooks to the components. The simulator's controls (match and broadcast) sit in their own panel, hidden when the engine has no simulator; the viewer's DVR controls work on any feed |
| `src/api.ts` | Typed client for `/api/matches`, `GET`/`POST /api/broadcast` (the simulator) and `POST /api/control` (the engine's DVR); failures throw `ApiError` (the engine's `{"error": ...}` message, or "engine unavailable") |
| `src/matchState.ts` | `matchReducer`: a pure function that builds the match (status, snapshots, alerts, incidents) from stream events, one at a time or in a batch; a `reset` starts it over |
| `src/useMatchStream.ts` | `useMatchStream`: follows `/api/stream` with `EventSource` and the reducer, applying messages in batches every 50 ms (a reconnect's backlog is thousands of messages, which would otherwise redraw the charts thousands of times), and reconnects when the browser gives up |
| `src/useBroadcast.ts` | `useBroadcast`: the match list and the simulator's broadcast status, from each command's reply plus a fetch on load and whenever the engine's state changes; ignores replies a later request has overtaken; `controllable` is false when the engine answers 404 (no simulator) |
| `src/useViewer.ts` | `useViewer`: sends the viewer's DVR commands, with an error and pending flag; the engine's new status arrives on the stream |
| `src/MatchPicker.tsx` | Chooses the match to load (named without its score); `App` then starts its broadcast |
| `src/BroadcastControls.tsx` | The broadcast's play/pause and speed presets (1×, 10×, 30×, 60×) |
| `src/ViewerControls.tsx` | The viewer's DVR: "LIVE" or how far behind it, play/pause, "Go live", speed presets, and a seek to a period and minute up to the live edge |
| `src/timeline.ts` | The time axis shared by the timeline, charts and feed: minutes played, each period starting where the previous one ended (stoppage time overlaps the next period's clock), labelled as match minutes ("45+3'"); `matchMinute` labels a single moment the same way, and `matchClock` to the second ("45+2:13") |
| `src/chartData.ts` | Snapshots for one window as chart points, home first; `matchTeams` takes home and away from the match list |
| `src/Scoreboard.tsx` | The score (and the shootout's), the clock to the second with stoppage time, the match state, and each team's goals and red cards; a goal disallowed after a review is struck through and comes off the score |
| `src/EventStrip.tsx` | The match timeline: goals, cards and penalties above the line, alerts below, stacked in lanes (`lanes.ts`) when close; hover or focus a marker for what it is |
| `src/MetricCharts.tsx` | The latest values head to head (`HeadToHead.tsx`), then field tilt (stacked to 100%), xT added and pressure per team, with a 5'/10' window toggle. Goals, disallowed goals, red cards and alerts are marked (`chartMarks.ts`; hover a marker for what it is), and the tooltip lists what happened near the hovered minute |
| `src/MatchFeed.tsx` | Events and alerts together, latest first, to the second, filterable (All / Events / Alerts). Each alert says whether its team scored in the next 10 minutes ("Scored 37s later", or "No goal in 10'") |
| `src/incidents.ts`, `src/alerts.ts` | Names, icons and descriptions of incidents and alert types; the score line; disallowed goals; `goalAfter`, the alerted team's goal within 10' |
| `src/Icons.tsx` | Inline SVG icons: ball, cards, penalty, VAR, the alert types, play and pause |
| `src/StatusBar.tsx` | The stream's connection and the engine's state; the last state stays on screen, dimmed, while reconnecting |
| `src/ui.ts` | Shared Tailwind classes |
| `src/index.css` | Tailwind CSS entry point and theme: Inter (self-hosted, `@fontsource-variable/inter`), the ink palette, team colours, the `card` and `eyebrow` utilities |
| `src/test/` | UI test setup (Testing Library matchers and cleanup) factories for API and stream messages, and a fake `EventSource` |
| `test/` | Contract tests: the shared schema fixtures against the JSON Schemas |

`src/schema/` is generated from `schema/jsonschema/` by `make gen`. Do not edit it by hand.
