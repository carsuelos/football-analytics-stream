import { useCallback, useState } from 'react'

/**
 * A yes/no the viewer chose (a section collapsed, the timeline expanded),
 * remembered in this browser. Where storage is unavailable it lasts the visit.
 */
export function useStoredFlag(key: string, initial: boolean): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState(() => read(key) ?? initial)
  const set = useCallback(
    (next: boolean) => {
      setValue(next)
      try {
        localStorage.setItem(key, next ? '1' : '0')
      } catch {
        // Private browsing or storage full: keep it for this visit only.
      }
    },
    [key],
  )
  return [value, set]
}

function read(key: string): boolean | null {
  try {
    const v = localStorage.getItem(key)
    return v === null ? null : v === '1'
  } catch {
    return null
  }
}
