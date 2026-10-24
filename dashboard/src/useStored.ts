import { useCallback, useState } from 'react'

/**
 * Choices the viewer made (a section folded, the timeline expanded, the order
 * of the Markets page's sections), remembered in this browser. Where storage
 * is unavailable they last the visit.
 */
function useStored<T>(key: string, initial: T, decode: (raw: string) => T | null, encode: (value: T) => string): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const raw = read(key)
    return (raw === null ? null : decode(raw)) ?? initial
  })
  const set = useCallback(
    (next: T) => {
      setValue(next)
      try {
        localStorage.setItem(key, encode(next))
      } catch {
        // Private browsing or storage full: keep it for this visit only.
      }
    },
    [key, encode],
  )
  return [value, set]
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

const decodeFlag = (raw: string) => raw === '1'
const encodeFlag = (v: boolean) => (v ? '1' : '0')

/** A yes/no. */
export function useStoredFlag(key: string, initial: boolean) {
  return useStored(key, initial, decodeFlag, encodeFlag)
}

const encodeList = (v: string[]) => JSON.stringify(v)

/**
 * An order of known items. A stored order keeps only the items still known,
 * and any new ones go at the end, so it survives items being added or removed.
 */
export function useStoredOrder<T extends string>(key: string, items: readonly T[]): [T[], (order: T[]) => void] {
  const decode = (raw: string): T[] | null => {
    try {
      const stored = JSON.parse(raw) as unknown
      if (!Array.isArray(stored)) return null
      const kept = items.filter((i) => stored.includes(i)).sort((a, b) => stored.indexOf(a) - stored.indexOf(b))
      return [...kept, ...items.filter((i) => !kept.includes(i))]
    } catch {
      return null
    }
  }
  return useStored<T[]>(key, [...items], decode, encodeList)
}
