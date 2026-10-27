# livefeed

Records [Sportmonks](https://www.sportmonks.com)' live matches to tapes, as they arrive. It's the first step towards a live feed for the engine: the tapes show what a real provider sends and how fast. They can be replayed offline, as tests, for tuning, and as training data. Turning them into canonical events for the `events` topic comes next (docs/PLAN.md, Phase 5).

```sh
cp .env.example .env              # once, at the repo root: put your Sportmonks token in it
make livefeed                     # record until stopped (Ctrl-C); ARGS="-for 3h" to stop by itself
make livefeed-tapes               # what each tape holds
```

The free plan covers the Scottish Premiership and the Danish Superliga, so record when they play. It's enough to build the plumbing on, but thin (checked Oct 26, 2026):

- **Has:** events (goals, cards, subs, VAR, penalties, to the minute), scores, periods (each half's start and end as timestamps, and the time added), lineups, and six statistics per team: goals, assists, possession %, corners, successful dribbles % and yellow cards.
- **Doesn't have:** `trends` and `ballCoordinates` (refused) and the paid add-ons.
- **Calls:** 180 an hour, so about one poll every 20 s. Paid plans have 2,000+ an hour.

## What it does

- **Polls** `GET /v3/football/livescores`: every match from 15 minutes before kick-off to 15 minutes after full time, in one call. It polls every 3 s (`-interval`) while a match is listed and every 2 minutes (`-idle-interval`) otherwise. It never goes faster than the plan allows: it spreads the hour's remaining calls over the rest of the hour, about one every 20 s on the free plan. It waits when the calls are used up, backs off when the API fails, and stops on another 4xx, such as a bad token.
- **Includes** `participants;scores;periods;state;events;statistics;trends;lineups;ballCoordinates` by default (`-includes` to change it). An include the plan refuses is dropped, with a warning, and the recording carries on without it. `pressure` and `xGFixture` are paid add-ons.
- **Writes** one tape per match: `data/livefeed/<UTC date>/<fixture id>.jsonl`. A tape starts with a keyframe (the whole fixture as sent). Each later line holds only what changed:
  - `set`: changed fields;
  - `unset`: fields that disappeared;
  - `upsert`: new or changed elements of a list with ids (events, ball positions, statistics…);
  - `remove`: elements that disappeared, such as a goal ruled out by VAR.

  There's another keyframe every 5 minutes. Without this, a match's few hundred ball positions sent every 3 s would come to about 70 MB an hour; with it, a match is a few MB. Each line has the time it was received, to measure the feed's delay.
- **Saves the type catalogue** (what each `type_id` means) once, to `data/livefeed/types.json`.

The token comes from `SPORTMONKS_API_TOKEN` and is only ever sent in the `Authorization` header, so it never appears in a URL, an error or a log line.

## Layout

| Path | What |
| --- | --- |
| `cmd/livefeed` | The recorder (`-record DIR`) and the tapes' summary (`-summary DIR`) |
| `internal/sportmonks` | The API client: livescores and the type catalogue |
| `internal/tape` | Writes tapes (keyframes and changes) and replays them into each fixture as it was received; `Summarize` |
