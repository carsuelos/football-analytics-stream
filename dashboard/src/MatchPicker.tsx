import type { MatchInfo } from './schema/match_list.schema'

interface Props {
  matches: MatchInfo[] | null
  /** The loaded match, if any. */
  matchId?: number
  disabled: boolean
  onLoad: (matchId: number) => void
}

/** Picks the match for the simulator to load. */
export function MatchPicker({ matches, matchId, disabled, onLoad }: Props) {
  return (
    <select
      aria-label="Match"
      value={matchId ?? ''}
      disabled={disabled || matches === null}
      onChange={(e) => onLoad(Number(e.target.value))}
      className="rounded-md bg-slate-800 px-3 py-1.5 text-sm disabled:opacity-50"
    >
      <option value="" disabled>
        {matches === null ? 'Loading matches…' : 'Choose a match…'}
      </option>
      {matches?.map((m) => (
        <option key={m.match_id} value={m.match_id}>
          {matchLabel(m)}
        </option>
      ))}
    </select>
  )
}

/** Names a match without its score, so a replay doesn't spoil the result. */
const matchLabel = (m: MatchInfo) =>
  `${m.home_team.name} v ${m.away_team.name} · ${m.competition} ${m.stage} · ${m.date}`
