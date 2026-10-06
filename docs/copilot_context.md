# Copilot Context: Live Football Analytics Stream

## 1. Project Overview & Vision
This project is an event-driven, real-time sports analytics engine built to process live match feeds, evaluate continuous pressure and territorial control, and surface high-value predictive insights as a match unfolds. Rather than treating match data as static historical records, the system treats incoming events as a live, streaming time-series to model momentum shifts dynamically.

## 2. Core Functional Domains & Features

### A. Stream Ingestion & Playback Simulation
* **Data Source Foundation:** Utilizes structured event data (such as StatsBomb open specifications) containing granular timestamps, event types, spatial coordinates, and team possessions.
* **Stream Simulation Layer:** Implements a controlled playback mechanism that reads raw event payloads and pushes them through a managed internal channel. This simulates a real-time 90-minute WebSocket or live broker feed, complete with pause, resume, speed adjustment, and time-skipping capabilities.
* **Clock & Sequence Synchronization:** Maintains an internal match clock state that handles stoppage time, halves, and out-of-order event safety.

### B. Rolling State Management & Metrics Engine
* **Sliding Time-Windows:** Implements sliding window aggregations (e.g., rolling 5-minute and 10-minute intervals) to calculate recent team activity rather than cumulative match totals.
* **Territorial & Positional Metrics:**
  * **Field Tilt:** Measures territorial dominance by calculating the ratio of final-third entries and touches between competing teams within active windows.
  * **Expected Threat (xThreat / xT):** Evaluates ball progression across the pitch, assigning value changes based on spatial location transitions to quantify dangerous attacks.
  * **Sustained Pressure Indices:** Tracks consecutive actions, recoveries in the attacking half, and prolonged sequences in the opponent's box.

### C. Predictive Intelligence & Tactical Alerting
* **Momentum Anomaly Detection:** Flags sudden, statistically significant shifts in pressure or territorial control that deviate from the match baseline.
* **Predictive Match Signals:** Generates high-value operational alerts based on active rolling thresholds, including:
  * Estimating the probability of a goal occurring within the next $X$ minutes based on current sustained pressure density and xT velocity.
  * Identifying momentum trends to highlight the likely next team to score or seize control of the match tempo.
* **Notification Routing:** Dispatches structured event payloads to downstream sinks (such as webhook endpoints, logging layers, or display interfaces) when alert conditions are triggered.

### D. Cloud-Native Operations & Infrastructure
* **Containerization:** Designed for clean packaging into isolated container runtimes.
* **Scalable State & Messaging:** Utilizes external brokers for event distribution and high-performance caching layers for ephemeral window state management.
* **Automation & CI/CD:** Incorporates automated validation pipelines to ensure repository integrity and continuous integration health across changes.

## 3. Collaborative Workflow & Intent
* **Baseline Reference:** This document serves as the structural reference for the project's features, objectives, and domain concepts.
* **Interactive Design:** Specific implementation patterns, data schemas, module boundaries, concurrency controls, and algorithmic details are intentionally left open to be designed interactively through planning sessions and iterative prompting.

## 4. Decisions
Decisions from planning sessions. The full roadmap and design rules are in [`PLAN.md`](PLAN.md).

| Area | Decision | Alternatives considered |
|---|---|---|
| Project goals | Portfolio piece, personal match-watching tool and product prototype; also a way to learn Go | — |
| Languages | Go for the stream simulator; Python for the analytics engine; TypeScript for the dashboard | Go for the whole live pipeline (more Go, slower MVP); all Python |
| Infrastructure | Phased: in-memory (Phase 1) → Docker Compose with a broker (Phase 2) → Azure (Phase 4). Interfaces behave like a broker log from day one (stable IDs, offsets, safe-to-repeat processing, seek to offset). Redis only if justified (several engine instances or crash recovery) | Real broker and cache from day one; in-memory only |
| Schema | JSON Schema in `schema/` as the single source of truth. Types generated for Python (pydantic), TS and Go. Shared fixtures are tested in every language; messages carry `schema_version` | Protobuf + `buf`; hand-written types |
| Simulator → engine link | WebSocket, one JSON event per message, each with an `offset`; resume with `?from_offset=N`. Playback controls go over a separate HTTP API | SSE; gRPC streaming |
| Data | StatsBomb open data replay, starting with the 2022 FIFA World Cup. The final (Argentina vs France) is the fixed end-to-end test match. A pluggable source adapter leaves room for a live provider later | Real live provider now |
| Match concurrency | One match at a time in v1; all state, topics and APIs keyed by `match_id` | Several matches at once from the start |
| Persistence | None in v1 (log sink only); add a database when needed | SQLite in v1; Postgres in Phase 2 |
| Dashboard | React + Vite SPA over WS/SSE. Lean v1: match picker, controls, live charts, alert feed (pitch view later) | Svelte; FastAPI + HTMX; Streamlit/Dash |
| Prediction | Rule-based first (thresholds, z-scores against the match baseline); trained, calibrated model in Phase 3 | Machine learning from the start; rules only |
| xT | Start with Karun Singh's published 12×8 grid; compute our own in Phase 3 and compare | — |
| Broker (Phase 2) | Redpanda locally through a standard Kafka client, so it moves to Azure Event Hubs with only config changes | Redis Streams |
| Cloud | Azure (Visual Studio subscription credit). Container Apps for the simulator and engine; Static Web Apps for the dashboard; Event Hubs Standard (Kafka); Container Registry; Log Analytics + App Insights; Key Vault. GitHub Actions deploys via OIDC | AKS; App Service; a single VM with Docker Compose |
| Infrastructure as code | Bicep; the costly resources can be torn down and recreated to save credit | Terraform |
| Dashboard access | Shared password or Container Apps' built-in Microsoft account sign-in; playback controls are never public | Fully public |

**Still open:** Azure region; which dashboard sign-in option; goal window X and alert thresholds (tuned in Phase 3); whether generated code is committed.