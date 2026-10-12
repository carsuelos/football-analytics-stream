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
| `src/App.tsx` | Page layout |
| `src/api.ts` | Typed client for `/api/matches`, `/api/playback` and `POST /api/control`; failures throw `ApiError` (the engine's `{"error": ...}` message, or "engine unavailable") |
| `src/matchState.ts` | `matchReducer`: a pure function that builds the match (status, snapshots, alerts) from stream events; a `reset` starts it over |
| `src/useMatchStream.ts` | `useMatchStream`: follows `/api/stream` with `EventSource` and the reducer, and reconnects when the browser gives up |
| `src/index.css` | Tailwind CSS entry point and theme (team colours) |
| `src/test/` | UI test setup (Testing Library matchers and cleanup) and factories for stream messages |
| `test/` | Contract tests: the shared schema fixtures against the JSON Schemas |

`src/schema/` is generated from `schema/jsonschema/` by `make gen`. Do not edit it by hand.
