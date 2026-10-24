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
| `src/AnalyticsPage.tsx` | The match analytics page; wires the stream, broadcast and viewer hooks to the components. The simulator's controls (match and broadcast) sit in their own panel, hidden when the engine has no simulator; the viewer's DVR controls work on any feed |
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
| `src/Scoreboard.tsx` | A compact scoreboard at the head of the match timeline (it stays in view while scrolling the charts): the score (and the shootout's), the clock to the second with stoppage time, the match state, and each team's goals and red cards; a goal disallowed after a review is struck through and comes off the score |
| `src/EventStrip.tsx` | The match timeline: goals, cards and penalties above the line, alerts below; hover or focus a marker for what it is. Compact (one row of small markers) until clicked or expanded, then stacked in lanes (`lanes.ts`) when close; `useStored.ts` remembers the choice, as it does the Markets page's folded and reordered sections |
| `src/MetricCharts.tsx` | The latest values head to head (`HeadToHead.tsx`), then field tilt (stacked to 100%), xT added and pressure per team, with a 5'/10' window toggle. Goals, disallowed goals, red cards and alerts are marked (`chartMarks.ts`; hover a marker for what it is), and the tooltip lists what happened near the hovered minute |
| `src/MatchFeed.tsx` | Events and alerts together, latest first, to the second, with Alerts / Goals / Cards / Penalties toggles (and how many of each; cards and penalties start hidden). Each alert says whether its team scored in the next 10 minutes: "Watching · 6' left" while the window is open, then "Scored 37s later" or "No goal in 10'" ("No goal by full time" when play ends first, as it has in the shootout). This is worked out in the browser from the goals the viewer has seen so far; the alert itself never changes |
| `src/incidents.ts`, `src/alerts.ts` | Names, icons and descriptions of incidents and alert types; the score line; disallowed goals; `goalAfter`, the alerted team's goal within 10' |
| `src/Icons.tsx` | Inline SVG icons: ball, cards, penalty, VAR, the alert types, play and pause |
| `src/StatusBar.tsx` | The stream's connection and the engine's state; the last state stays on screen, dimmed, while reconnecting |
| `nginx.conf.template`, `19-basic-auth.envsh` | The production server: the build, `/api` proxied to the engine (re-resolved, unbuffered for the stream), and a shared password by basic auth when `DASHBOARD_PASSWORD` is set (as in Azure; `/healthz` is open for probes) |
| `src/App.tsx`, `src/useRoute.ts` | The header and the page the URL's hash names: `#/` the match analytics (`AnalyticsPage.tsx`), `#/markets` the prediction markets. Only the page shown is mounted, so only it streams or polls |
| `src/MatchLibrary.tsx` | **+ Add matches**: every competition season from 2000 on in StatsBomb's open data (`/api/library`, the simulator's library), searchable and filtered by women's or men's and, by default, to seasons the models haven't seen (`in_training` tags the rest), with a button to download one into the simulator and its progress; the match list refreshes when it ends. Hidden where the simulator can't download (the cloud's data is read-only) |
| `public/manifest.webmanifest`, `public/app-icon.svg` | The dashboard as an installable app (Safari ▸ File ▸ Add to Dock), so its notifications show its icon, not Safari's |
| `src/notifications.ts`, `src/AlertToasts.tsx`, `src/NotifySettings.tsx` | New alerts announced: a pop-up at the top right (10 s, at most 3), a ding (Web Audio, no sound file; on by default), and, with **Notify me**, a system notification (Notification Centre on a Mac) while the window is in the background. New means within 60 s of match time of the viewer's position, so the history the engine sends on a connect or seek isn't announced; each alert once per page. Settings remembered |
| `src/ThemeToggle.tsx` | The header's dark/light switch, remembered in this browser (`index.html` applies it before the first paint). The light theme is `html.light` in `index.css`: the same classes with the palette turned over, so components need nothing theme-specific; charts take their grid colours from CSS variables |
| `src/MarketsPage.tsx` | The prediction markets for a league (`/api/markets`, the `markets` service): the venues' status, the games (`GameList.tsx`), a game's contracts priced on each venue with the cheapest all-in (`GameMarkets.tsx`; its sections fold and reorder by their handles), its best price over time (`PriceChart.tsx`), and the trading to come (`Trading.tsx`: the strategy, paper results, and each venue's key for real money; all off until the live feed). `usePolled.ts` polls, `marketsApi.ts` fetches, `venues.ts` names and formats |
| `src/ui.ts` | Shared Tailwind classes |
| `src/index.css` | Tailwind CSS entry point and theme: Inter (self-hosted, `@fontsource-variable/inter`), the ink palette, team colours, the `card` and `eyebrow` utilities |
| `src/test/` | UI test setup (Testing Library matchers and cleanup) factories for API and stream messages, and a fake `EventSource` |
| `test/` | Contract tests: the shared schema fixtures against the JSON Schemas |

`src/schema/` is generated from `schema/jsonschema/` by `make gen`. Do not edit it by hand.
