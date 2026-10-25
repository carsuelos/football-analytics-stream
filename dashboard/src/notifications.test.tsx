import { act, render, renderHook, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AlertToasts } from './AlertToasts'
import { MAX_TOASTS, TOAST_MS, useAlertNotifications, useNotifySetting } from './notifications'
import { NotifySettings } from './NotifySettings'
import type { Alert } from './schema/alert.schema'
import type { EngineStatus } from './schema/engine_status.schema'
import { alert, ARGENTINA, FRANCE, status } from './test/factories'

class FakeNotification {
  static permission: NotificationPermission = 'granted'
  static requestPermission = vi.fn(async () => FakeNotification.permission)
  static shown: FakeNotification[] = []
  onclick: (() => void) | null = null
  close = vi.fn()
  title: string
  options: NotificationOptions
  constructor(title: string, options: NotificationOptions) {
    this.title = title
    this.options = options
    FakeNotification.shown.push(this)
  }
}

/** Counts the dings. */
class FakeAudio {
  static notes = 0
  currentTime = 0
  destination = {}
  createOscillator() {
    FakeAudio.notes++
    return { type: '', frequency: { value: 0 }, connect: (n: unknown) => n, start() {}, stop() {} }
  }
  createGain() {
    const node = { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (n: unknown) => n }
    return node
  }
}

let focused = false

beforeEach(() => {
  FakeNotification.permission = 'granted'
  FakeNotification.shown = []
  FakeAudio.notes = 0
  focused = false
  vi.stubGlobal('Notification', FakeNotification)
  vi.stubGlobal('AudioContext', FakeAudio)
  vi.spyOn(document, 'hasFocus').mockImplementation(() => focused)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const teams = [ARGENTINA, FRANCE]
const at = (match_clock_s: number, overrides: Partial<EngineStatus> = {}) => status({ period: 2, match_clock_s, ...overrides })
const both = { system: true, sound: true }

function announcing(alerts: Alert[], s: EngineStatus, settings = both) {
  return renderHook(({ alerts, s, settings }) => useAlertNotifications(settings, alerts, s, teams), { initialProps: { alerts, s, settings } })
}

it('pops up, dings and notifies the Mac of a new alert, once, with its team and moment', () => {
  const a = alert()
  const { result, rerender } = announcing([a], at(4950))
  expect(result.current.toasts).toEqual([{ id: a.id, alert: a, title: 'Control · France', body: `82:27 · ${a.message}` }])
  expect(FakeAudio.notes).toBe(2)
  expect(FakeNotification.shown.map((n) => n.title)).toEqual(['Control · France'])
  rerender({ alerts: [a], s: at(4960), settings: both })
  expect(result.current.toasts).toHaveLength(1)
  expect(FakeNotification.shown).toHaveLength(1)
  FakeNotification.shown[0].onclick!()
  expect(FakeNotification.shown[0].close).toHaveBeenCalled()
})

it('leaves the full-time part of a message to the feed', () => {
  const a = alert({ message: "Argentina: 19% in the next 10'. By full time: 63% to score again" })
  const { result } = announcing([a], at(4950))
  expect(result.current.toasts[0].body).toBe("82:27 · Argentina: 19% in the next 10'")
})

it("doesn't announce the history sent on a connect or seek, or while rebuilding", () => {
  const { result } = announcing([alert({ match_clock_s: 4000 }), alert({ id: 'other-half', period: 1, match_clock_s: 4940 })], at(4950))
  const rebuilding = announcing([alert({ id: 'b' })], at(4950, { state: 'rebuilding' }))
  expect(result.current.toasts).toEqual([])
  expect(rebuilding.result.current.toasts).toEqual([])
  expect(FakeAudio.notes + FakeNotification.shown.length).toBe(0)
})

it('only pops up while the window is focused, and is silent with the sound off', () => {
  focused = true
  const { result } = announcing([alert()], at(4950), { system: true, sound: false })
  expect(result.current.toasts).toHaveLength(1)
  expect(FakeNotification.shown).toHaveLength(0)
  expect(FakeAudio.notes).toBe(0)
})

it('keeps the latest few pop-ups, which close by themselves or when closed', async () => {
  vi.useFakeTimers()
  const alerts = Array.from({ length: MAX_TOASTS + 1 }, (_, i) => alert({ id: `a${i}`, match_clock_s: 4940 + i }))
  const { result, rerender } = announcing(alerts, at(4950))
  expect(result.current.toasts.map((t) => t.id)).toEqual(['a1', 'a2', 'a3'])
  const { rerender: show } = render(<AlertToasts toasts={result.current.toasts} teams={teams} onDismiss={result.current.dismiss} />)
  act(() => screen.getAllByRole('button', { name: 'Close' })[0].click())
  rerender({ alerts, s: at(4951), settings: both })
  expect(result.current.toasts.map((t) => t.id)).toEqual(['a2', 'a3'])
  show(<AlertToasts toasts={result.current.toasts} teams={teams} onDismiss={result.current.dismiss} />)
  expect(within(screen.getByRole('list', { name: 'New alerts' })).getAllByRole('listitem')).toHaveLength(2)
  act(() => vi.advanceTimersByTime(TOAST_MS))
  expect(result.current.toasts).toEqual([])
})

it('announces the latest alert, or a sample, on test, Mac notification included', () => {
  focused = true
  const { result } = announcing([], at(4950))
  act(() => result.current.test())
  expect(result.current.toasts[0].body).toMatch(/A test/)
  // The sample is a model alert: its own title mark and three-note chime.
  expect(FakeNotification.shown.map((n) => n.title)).toEqual(['⚡ Goal chance (model)'])
  expect(FakeAudio.notes).toBe(3)
})

it('sends a test on Option-click instead of toggling', async () => {
  const onTest = vi.fn()
  render(<NotifySettings system={{ on: true, permission: 'granted', toggle: async () => {} }} sound onSound={() => {}} onTest={onTest} />)
  const user = userEvent.setup()
  await user.keyboard('{Alt>}')
  await user.click(screen.getByRole('switch', { name: 'Notify me' }))
  await user.keyboard('{/Alt}')
  expect(onTest).toHaveBeenCalledOnce()
})

function Settings({ sound = true }: { sound?: boolean }) {
  return <NotifySettings system={useNotifySetting()} sound={sound} onSound={() => {}} onTest={() => {}} />
}

it('asks for permission when Mac notifications are turned on, and remembers the choice', async () => {
  FakeNotification.permission = 'default'
  FakeNotification.requestPermission.mockImplementationOnce(async () => {
    FakeNotification.permission = 'granted'
    return 'granted'
  })
  const { unmount } = render(<Settings />)
  const toggle = screen.getByRole('switch', { name: 'Notify me' })
  expect(toggle).not.toBeChecked()
  expect(screen.getByRole('switch', { name: 'Sound' })).toBeChecked()
  await userEvent.click(toggle)
  expect(FakeNotification.requestPermission).toHaveBeenCalled()
  expect(toggle).toBeChecked()
  unmount()
  render(<Settings />)
  expect(screen.getByRole('switch', { name: 'Notify me' })).toBeChecked()
})

it('says when the browser blocks notifications', () => {
  render(<NotifySettings system={{ on: false, permission: 'denied', toggle: async () => {} }} sound={false} onSound={() => {}} onTest={() => {}} />)
  expect(screen.getByRole('switch', { name: 'Notifications blocked' })).toBeDisabled()
  expect(screen.getByRole('switch', { name: 'Sound' })).not.toBeChecked()
})
