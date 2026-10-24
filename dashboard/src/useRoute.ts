import { useSyncExternalStore } from 'react'

/** The dashboard's pages, chosen by the URL's hash: #/ (or none) and #/markets. */
export type Route = 'analytics' | 'markets'

export const routeOf = (hash: string): Route => (hash.startsWith('#/markets') ? 'markets' : 'analytics')

export const hrefOf = (route: Route) => (route === 'markets' ? '#/markets' : '#/')

const subscribe = (onChange: () => void) => {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

/** The page the URL is on, following the back and forward buttons. */
export function useRoute(): Route {
  return useSyncExternalStore(subscribe, () => routeOf(window.location.hash))
}
