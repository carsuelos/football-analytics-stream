import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, downloadSeason, getLibrary } from './api'
import type { LibrarySeason, MatchLibrary as Library } from './schema/match_library.schema'
import { buttonClass, segmentClass, segmentsClass } from './ui'
import { useStoredFlag } from './useStored'

/** How often the dialog checks a download's progress. */
export const LIBRARY_POLL_MS = 1000

type Who = 'all' | 'female' | 'male'

/**
 * "Add matches": every competition season in StatsBomb's open data, and a
 * button to download one into the simulator, in the background. When a
 * download finishes, onDownloaded refreshes the match list. Hidden where the
 * simulator can't download (the cloud deployment's data is read-only).
 */
export function AddMatches({ onDownloaded }: { onDownloaded: () => void }) {
  const [open, setOpen] = useState(false)
  const [available, setAvailable] = useState(true)
  useEffect(() => {
    getLibrary().catch((e: unknown) => e instanceof ApiError && e.status === 404 && setAvailable(false))
  }, [])
  if (!available) return null
  return (
    <>
      <button type="button" className={buttonClass} onClick={() => setOpen(true)}>
        + Add matches
      </button>
      {open && <LibraryDialog onClose={() => setOpen(false)} onDownloaded={onDownloaded} />}
    </>
  )
}

function LibraryDialog({ onClose, onDownloaded }: { onClose: () => void; onDownloaded: () => void }) {
  const [library, setLibrary] = useState<Library | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [who, setWho] = useState<Who>('all')
  // A season the models trained on isn't a fair test of them, so by default they're hidden.
  const [unseenOnly, setUnseenOnly] = useStoredFlag('library.unseen', true)
  const search = useRef<HTMLInputElement>(null)
  const downloading = library?.download?.state === 'downloading'
  const wasDownloading = useRef(false)

  const load = useCallback(
    () =>
      getLibrary().then(
        (l) => (setLibrary(l), setError(null)),
        (e: unknown) => setError(e instanceof Error ? e.message : String(e)),
      ),
    [],
  )
  useEffect(() => {
    void load()
    search.current?.focus()
  }, [load])
  // While a download runs, follow it; when it ends, the match list has more.
  useEffect(() => {
    if (downloading) {
      wasDownloading.current = true
      const timer = setInterval(() => void load(), LIBRARY_POLL_MS)
      return () => clearInterval(timer)
    }
    if (wasDownloading.current) {
      wasDownloading.current = false
      onDownloaded()
    }
  }, [downloading, load, onDownloaded])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const start = (s: LibrarySeason) =>
    downloadSeason(s.competition_id, s.season_id).then(
      (l) => (setLibrary(l), setError(null)),
      (e: unknown) => setError(e instanceof Error ? e.message : String(e)),
    )

  const seasons = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean)
    return (library?.seasons ?? []).filter(
      (s) =>
        (who === 'all' || s.gender === who) &&
        (!unseenOnly || !s.in_training) &&
        words.every((w) => `${s.competition} ${s.season} ${s.country ?? ''}`.toLowerCase().includes(w)),
    )
  }, [library, query, who, unseenOnly])
  const d = library?.download

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="library-title"
        className="card flex max-h-[85vh] w-full max-w-2xl flex-col gap-3 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3">
          <div>
            <h2 id="library-title" className="text-lg font-semibold">
              Add matches
            </h2>
            <p className="text-xs text-slate-500">
              From StatsBomb's open data (free for non-commercial use). Downloaded matches join the simulator's list.
            </p>
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-md px-2 text-xl text-slate-400 hover:bg-white/10 hover:text-slate-100">
            ×
          </button>
        </header>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={search}
            type="search"
            aria-label="Search"
            placeholder="Search: euro 2025, premier league…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-ink-800 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500"
          />
          <div role="group" aria-label="Who" className={segmentsClass}>
            {(['all', 'female', 'male'] as const).map((w) => (
              <button key={w} type="button" className={segmentClass} aria-pressed={who === w} onClick={() => setWho(w)}>
                {{ all: 'All', female: "Women's", male: "Men's" }[w]}
              </button>
            ))}
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300" title="The models were trained on every men's senior season from 2003 (except the 2022 World Cup they're tested on): replaying those is fine to watch, but not a fair test of the alerts">
          <input type="checkbox" checked={unseenOnly} onChange={(e) => setUnseenOnly(e.target.checked)} />
          Only seasons the model hasn't seen
        </label>
        {d && <DownloadProgress download={d} />}
        {(error ?? library?.error) && (
          <p role="alert" className="rounded-lg border border-red-400/20 bg-red-400/10 px-3 py-2 text-sm text-red-300">
            {error ?? `Couldn't refresh the list from StatsBomb: ${library?.error}`}
          </p>
        )}
        <ul aria-label="Seasons" className="-mx-2 min-h-40 overflow-y-auto">
          {!library && !error && <li className="px-2 py-8 text-center text-sm text-slate-400">Loading StatsBomb's seasons…</li>}
          {library && seasons.length === 0 && <li className="px-2 py-8 text-center text-sm text-slate-400">No seasons match.</li>}
          {seasons.map((s) => {
            const busy = d?.state === 'downloading' && d.competition_id === s.competition_id && d.season_id === s.season_id
            const complete = s.matches !== undefined && s.downloaded >= s.matches
            return (
              <li key={`${s.competition_id}-${s.season_id}`} className="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-white/[0.03]">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-sm font-medium text-slate-100">
                    <span className="truncate">
                      {s.competition} <span className="text-slate-400">{s.season}</span>
                    </span>
                    {s.in_training && (
                      <span title="The models were trained on this season: not a fair test of them" className="shrink-0 rounded-full bg-amber-400/10 px-1.5 py-px text-[10px] font-semibold text-amber-300/90">
                        In training
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-500">
                    {[s.country, s.gender === 'female' ? "Women's" : "Men's", s.youth ? 'Youth' : null].filter(Boolean).join(' · ')}
                    {s.downloaded > 0 && ` · ${s.downloaded}${s.matches !== undefined ? ` of ${s.matches}` : ''} matches downloaded`}
                  </p>
                </div>
                {complete ? (
                  <span className="text-xs font-semibold text-emerald-300">Downloaded ✓</span>
                ) : (
                  <button
                    type="button"
                    className={buttonClass}
                    disabled={downloading}
                    aria-label={`Download ${s.competition} ${s.season}`}
                    onClick={() => void start(s)}
                  >
                    {busy ? 'Downloading…' : s.downloaded > 0 ? 'Finish download' : 'Download'}
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}

function DownloadProgress({ download: d }: { download: NonNullable<Library['download']> }) {
  const share = d.total > 0 ? d.done / d.total : 0
  const label = {
    downloading: `Downloading ${d.competition} ${d.season}: ${d.done} of ${d.total || '…'} matches`,
    done: `Downloaded ${d.competition} ${d.season}: ${d.total} matches, now in the match list`,
    failed: `Download of ${d.competition} ${d.season} stopped: ${d.error ?? 'failed'}. Try again to fetch the rest.`,
  }[d.state]
  return (
    <div role="status" className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
      <p className={`text-sm ${d.state === 'failed' ? 'text-red-300' : d.state === 'done' ? 'text-emerald-300' : 'text-slate-200'}`}>{label}</p>
      {d.state === 'downloading' && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
          <div className="h-full rounded-full bg-sky-400 transition-[width]" style={{ width: `${share * 100}%` }} />
        </div>
      )}
    </div>
  )
}
