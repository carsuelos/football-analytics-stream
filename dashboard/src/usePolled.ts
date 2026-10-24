import { useEffect, useRef, useState } from 'react'

export interface Polled<T> {
  /** The latest reply, kept while a newer one is on its way or failed. */
  data: T | null
  /** The last request's error, cleared by the next success. */
  error: string | null
}

/**
 * Fetches with load every intervalMs while mounted, and again from scratch
 * whenever key changes (its data is dropped, as it was for another key). A
 * request still in flight is aborted when the next starts or on unmount. A
 * null key fetches nothing.
 */
export function usePolled<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>, intervalMs: number): Polled<T> {
  const [state, setState] = useState<Polled<T> & { key: string | null }>({ key, data: null, error: null })
  // The latest load, so a poll uses the current one without restarting the timer.
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })
  if (state.key !== key) {
    setState({ key, data: null, error: null })
  }
  useEffect(() => {
    if (key === null) return
    let controller: AbortController | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false
    const poll = async () => {
      controller = new AbortController()
      try {
        const data = await loadRef.current(controller.signal)
        if (!stopped) setState({ key, data, error: null })
      } catch (e) {
        if (!stopped && !controller.signal.aborted) {
          setState((s) => ({ ...s, key, error: e instanceof Error ? e.message : String(e) }))
        }
      }
      if (!stopped) timer = setTimeout(() => void poll(), intervalMs)
    }
    void poll()
    return () => {
      stopped = true
      clearTimeout(timer)
      controller?.abort()
    }
  }, [key, intervalMs])
  return { data: state.data, error: state.error }
}
